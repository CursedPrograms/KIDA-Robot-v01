# mapper/build_3d_map.py — offline 3D map builder
#
# Run this AFTER stopping kida-robot.service (`sudo systemctl stop
# kida-robot.service`) — that's what frees the Hailo-8L entirely for this
# script, instead of sharing it through the SHARED round-robin group the
# live app's Whisper/face-emotion/lane-detect threads use.
#
# Pipeline for one sweep_id (see scripts/lidar_sweep.py):
#   1. Read that sweep's (angle, us1_cm, laser_mm, pose, frame_path) points
#      from data/kida.db.
#   2. Run a Hailo monocular depth-estimation model (DeGirum PySDK — the
#      other Hailo consumers in this project use raw hailo_platform
#      instead, but this model's postprocessing is DeGirum-specific, see
#      examples/022_monocular_depth_estimation.ipynb) on the sweep's
#      tagged reference frame.
#   3. Calibrate the model's relative depth output against the sweep's
#      real ultrasonic/laser readings (monocular depth models give
#      relative depth, not metric — the swept points are actual measured
#      centimeters, so use them to derive a real-world scale).
#   4. Decimate the depth map to a manageable point count and hand the
#      pixel+depth+pose data to fortran/libmap_accumulate.so for the
#      actual 3D projection + voxel-grid deduplication (see that file for
#      why the array math lives there instead of here).
#   5. Write the result as an ASCII PLY point cloud, plus a flat stats
#      text file for cobol/map-summary.cob to report on.
#
# ⚠️ Status: the Fortran binding, sweep-data read, calibration math, and
# PLY writer are all tested against synthetic data in this file's
# __main__ self-test. The actual DeGirum depth-model inference call is
# NOT — running it needs the Hailo-8L idle (kida-robot.service stopped),
# which wasn't done to build this, so treat that one step as unverified
# until you run it for real.

import argparse
import ctypes
import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
import kida_db  # noqa: E402

FORTRAN_LIB = str(Path(__file__).resolve().parent.parent / "fortran" / "libmap_accumulate.so")
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

MODEL_NAME = "scdepthv3--256x320_quant_hailort_hailo8l_1"
CAM1_HFOV_DEG = 66.0   # approximation — this robot has no calibrated camera intrinsics
DECIMATE_STEP = 4      # sample every Nth pixel in each axis before projecting
VOXEL_CM = 5.0          # point-cloud dedup cell size


def _load_fortran_lib():
    lib = ctypes.CDLL(FORTRAN_LIB)
    lib.project_points.argtypes = [
        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    lib.voxel_bin.argtypes = [
        ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int),
    ]
    return lib


def _run_depth_model(image_path: str) -> np.ndarray:
    """Returns the model's raw per-pixel depth output, shape (H, W).
    UNVERIFIED against real hardware — see module docstring."""
    import degirum as dg
    import cv2

    def dequantize(result):
        zero_pt = result["quantization"]["zero"]
        scale = result["quantization"]["scale"]
        return (result["data"].astype(np.float32) - zero_pt) * scale

    def sigmoid(z):
        return 1 / (1 + np.exp(-z))

    class DepthResults(dg.postprocessor.InferenceResults):
        use_scdepth = True
        normalize_results = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            data = self._inference_results[0]["data"]
            if data.dtype.kind in ("u", "i"):
                data = dequantize(self._inference_results[0])
            data = data.squeeze(0)

            hwc_layout = self._model_params.InputTensorLayout[0] == "NHWC"
            shape_idxs = (0, 1) if hwc_layout else (1, 2)
            if (data.shape[shape_idxs[0]] != self._model_params.InputH[0]
                    or data.shape[shape_idxs[1]] != self._model_params.InputW[0]):
                data = np.reshape(data.squeeze(),
                                   (self._model_params.InputH[0], self._model_params.InputW[0], 1))
            if not hwc_layout:
                data = np.transpose(data, (1, 2, 0))

            if self.image is not None:
                resize_map = {"nearest": cv2.INTER_NEAREST, "bilinear": cv2.INTER_LINEAR,
                               "area": cv2.INTER_AREA, "bicubic": cv2.INTER_CUBIC,
                               "lanczos": cv2.INTER_LANCZOS4}
                resize_mode = resize_map[self._model_params.InputResizeMethod[0]]
                image_size = self.image.shape[:2][::-1]
                data = cv2.resize(data, image_size, interpolation=resize_mode)
                data = np.expand_dims(data, axis=0)

            if DepthResults.use_scdepth:
                data = 1 / (sigmoid(data) * 10 + 0.009)

            self._inference_results[0]["data"] = data

    model = dg.load_model(model_name=MODEL_NAME, inference_host_address="@local",
                           zoo_url="degirum/hailo", token="")
    model.custom_postprocessor = DepthResults
    result = model(image_path)
    return result._inference_results[0]["data"].squeeze()


def _calibrate_scale(depth_map: np.ndarray, sweep_rows: list, img_w: int) -> float:
    """Derive cm-per-depth-unit by comparing the depth map's value at each
    sweep angle's corresponding column (only angles within the camera's
    own FOV, centered on servo angle 90) against that point's real
    ultrasonic/laser reading. Returns the median ratio across matches."""
    half_fov = CAM1_HFOV_DEG / 2.0
    ratios = []
    for row in sweep_rows:
        angle, us1_cm, laser_mm, *_ = row
        offset = angle - 90
        if abs(offset) > half_fov:
            continue
        real_cm = us1_cm if us1_cm not in (None, 0) else (laser_mm / 10.0 if laser_mm else None)
        if real_cm is None or real_cm <= 0:
            continue
        col = int(img_w / 2 + (offset / CAM1_HFOV_DEG) * img_w)
        col = max(0, min(img_w - 1, col))
        row_px = depth_map.shape[0] // 2
        depth_val = float(depth_map[row_px, col])
        if depth_val > 0:
            ratios.append(real_cm / depth_val)
    if not ratios:
        raise ValueError("No sweep points fell within the camera's FOV to calibrate against")
    return float(np.median(ratios))


def _write_ply(path: Path, xs, ys, zs) -> None:
    with open(path, "w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(xs)}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("end_header\n")
        for x, y, z in zip(xs, ys, zs):
            f.write(f"{x:.2f} {y:.2f} {z:.2f}\n")


def build_map(sweep_id: str) -> Path:
    kida_db.init_db()
    with kida_db._connect() as conn:
        rows = conn.execute(
            "SELECT angle_deg, us1_cm, laser_mm, pos_x_cm, pos_y_cm, heading_deg, frame_path "
            "FROM sweep_log WHERE sweep_id = ? ORDER BY id", (sweep_id,)
        ).fetchall()
    if not rows:
        raise ValueError(f"No sweep_log rows found for sweep_id={sweep_id}")

    frame_path = next((r[6] for r in rows if r[6]), None)
    if not frame_path:
        raise ValueError(f"sweep_id={sweep_id} has no tagged reference frame")
    pos_x_cm, pos_y_cm, heading_deg = rows[0][3], rows[0][4], rows[0][5]

    depth_map = _run_depth_model(frame_path)
    img_h, img_w = depth_map.shape[:2]
    scale_cm = _calibrate_scale(depth_map, rows, img_w)

    us, vs, depths = [], [], []
    for v in range(0, img_h, DECIMATE_STEP):
        for u in range(0, img_w, DECIMATE_STEP):
            us.append(u); vs.append(v); depths.append(float(depth_map[v, u]))
    n = len(us)

    lib = _load_fortran_lib()
    u_arr = (ctypes.c_int * n)(*us)
    v_arr = (ctypes.c_int * n)(*vs)
    d_arr = (ctypes.c_double * n)(*depths)
    ox = (ctypes.c_double * n)(); oy = (ctypes.c_double * n)(); oz = (ctypes.c_double * n)()

    lib.project_points(n, u_arr, v_arr, d_arr, img_w, img_h, CAM1_HFOV_DEG, scale_cm,
                        pos_x_cm, pos_y_cm, heading_deg, ox, oy, oz)

    bx = (ctypes.c_double * n)(); by = (ctypes.c_double * n)(); bz = (ctypes.c_double * n)()
    count = ctypes.c_int(0)
    lib.voxel_bin(n, ox, oy, oz, VOXEL_CM, bx, by, bz, ctypes.byref(count))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ply_path = OUTPUT_DIR / f"{sweep_id}.ply"
    _write_ply(ply_path, bx[:count.value], by[:count.value], bz[:count.value])

    stats_path = OUTPUT_DIR / f"{sweep_id}_stats.txt"
    with open(stats_path, "w") as f:
        f.write(f"sweep_id: {sweep_id}\n")
        f.write(f"reference_frame: {frame_path}\n")
        f.write(f"sweep_points: {len(rows)}\n")
        f.write(f"depth_map_pixels_sampled: {n}\n")
        f.write(f"calibrated_scale_cm_per_unit: {scale_cm:.4f}\n")
        f.write(f"output_points_after_voxel_bin: {count.value}\n")
        f.write(f"ply_output: {ply_path}\n")

    print(f"✅ Map built: {count.value} points -> {ply_path}")
    return ply_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("sweep_id", nargs="?", help="sweep_id from lidar_sweep.py / kida_db.sweep_log")
    parser.add_argument("--self-test", action="store_true",
                         help="Verify the Fortran binding + PLY writer against synthetic data, no Hailo/DB needed")
    args = parser.parse_args()

    if args.self_test:
        lib = _load_fortran_lib()
        n = 16
        us = [i * 20 for i in range(n)]
        vs = [128] * n
        depths = [1.0] * n
        u_arr = (ctypes.c_int * n)(*us)
        v_arr = (ctypes.c_int * n)(*vs)
        d_arr = (ctypes.c_double * n)(*depths)
        ox = (ctypes.c_double * n)(); oy = (ctypes.c_double * n)(); oz = (ctypes.c_double * n)()
        lib.project_points(n, u_arr, v_arr, d_arr, 320, 256, CAM1_HFOV_DEG, 100.0, 0.0, 0.0, 0.0, ox, oy, oz)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _write_ply(OUTPUT_DIR / "selftest.ply", list(ox), list(oy), list(oz))
        print(f"✅ self-test OK — wrote {OUTPUT_DIR / 'selftest.ply'} ({n} points)")
    elif args.sweep_id:
        build_map(args.sweep_id)
    else:
        parser.error("provide a sweep_id, or --self-test")
