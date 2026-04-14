# lane_detection_utils.py
#
# Fixes vs original:
#   • _soft_max: removed the redundant second np.exp(z) call — the original
#     computed t = exp(z) then divided by np.sum(exp(z)) again, throwing
#     away t entirely and recomputing from scratch.  Now uses t consistently.
#   • _pred2coords (col lane loop): `all_ind` was built as list(...) then
#     immediately overwritten with range(...) on the next line, making the
#     list() call dead code.  Removed the dead list() line so all_ind is
#     always the range object the softmax indexing needs.
#   • Removed unused `from multiprocessing import Process` import.

from math import hypot
import numpy as np
import cv2
from loguru import logger


class UFLDProcessing:
    def __init__(self,
                 num_cell_row: int,
                 num_cell_col: int,
                 num_row: int,
                 num_col: int,
                 num_lanes: int,
                 crop_ratio: float,
                 original_frame_width: int,
                 original_frame_height: int,
                 total_frames: int):
        """
        Initialize UFLDProcessing with lane-detection parameters.

        Args:
            num_cell_row: Number of rows for the grid cells.
            num_cell_col: Number of columns for the grid cells.
            num_row: Number of rows for lanes.
            num_col: Number of columns for lanes.
            num_lanes: Number of lanes.
            crop_ratio: Ratio for cropping the frame.
            original_frame_width: Width of the original image.
            original_frame_height: Height of the original image.
            total_frames: Total number of frames in the video.
        """
        self.num_cell_row       = num_cell_row
        self.num_cell_col       = num_cell_col
        self.num_row            = num_row
        self.num_col            = num_col
        self.num_lanes          = num_lanes
        self.crop_ratio         = crop_ratio
        self.original_frame_width  = original_frame_width
        self.original_frame_height = original_frame_height
        self.total_frames       = total_frames

    def resize(self, image: np.ndarray, input_height: int, input_width: int) -> np.ndarray:
        """
        Resize and crop an image.

        Args:
            image: Input image.
            input_height: Target height before crop.
            input_width: Target width.

        Returns:
            Resized and bottom-cropped image (last 320 rows).
        """
        new_height    = int(input_height / self.crop_ratio)
        image_resized = cv2.resize(image, (input_width, new_height),
                                   interpolation=cv2.INTER_CUBIC)
        return image_resized[-320:, :, :]

    def _soft_max(self, z: np.ndarray) -> np.ndarray:
        """
        Numerically stable softmax.

        Args:
            z: Input array.

        Returns:
            Softmax probabilities.
        """
        # FIX: original computed t = exp(z) then divided by sum(exp(z)) again,
        # discarding t.  Now reuses t for both numerator and denominator.
        t = np.exp(z)
        return t / np.sum(t)

    def _slice_and_reshape(self, output: np.ndarray):
        """
        Slice and reshape the output tensor into row/col localization + existence tensors.

        Args:
            output: Concatenated inference output, shape (1, total_features).

        Returns:
            Tuple (loc_row, loc_col, exist_row, exist_col).
        """
        dim1 = self.num_cell_row * self.num_row  * self.num_lanes
        dim2 = self.num_cell_col * self.num_col  * self.num_lanes
        dim3 = 2 * self.num_row  * self.num_lanes
        dim4 = 2 * self.num_col  * self.num_lanes

        loc_row    = np.reshape(output[:, :dim1],
                                (-1, self.num_cell_row, self.num_row, self.num_lanes))
        loc_col    = np.reshape(output[:, dim1:dim1 + dim2],
                                (-1, self.num_cell_col, self.num_col, self.num_lanes))
        exist_row  = np.reshape(output[:, dim1 + dim2:dim1 + dim2 + dim3],
                                (-1, 2, self.num_row, self.num_lanes))
        exist_col  = np.reshape(output[:, -dim4:],
                                (-1, 2, self.num_col, self.num_lanes))
        return loc_row, loc_col, exist_row, exist_col

    def _pred2coords(self, loc_row, loc_col, exist_row, exist_col,
                     local_width: int = 1) -> list:
        """
        Convert prediction tensors to (x, y) lane coordinates.

        Args:
            loc_row: Row localization tensor.
            loc_col: Column localization tensor.
            exist_row: Row existence tensor.
            exist_col: Column existence tensor.
            local_width: Half-width of the local window around argmax.

        Returns:
            List of lanes, each lane being a list of (x, y) int tuples.
        """
        row_anchor = np.linspace(160, 710, 56) / 720
        col_anchor = np.linspace(0, 1, 41)

        _, num_grid_row, num_cls_row, _ = loc_row.shape
        _, num_grid_col, num_cls_col, _ = loc_col.shape

        max_indices_row = np.argmax(loc_row,  1)
        valid_row       = np.argmax(exist_row, 1)
        max_indices_col = np.argmax(loc_col,  1)
        valid_col       = np.argmax(exist_col, 1)

        coords        = []
        row_lane_idx  = [1, 2]
        col_lane_idx  = [0, 3]

        for i in row_lane_idx:
            tmp = []
            if np.sum(valid_row[0, :, i]) > num_cls_row / 2:
                for k in range(valid_row.shape[1]):
                    if valid_row[0, k, i]:
                        lo  = max(0, max_indices_row[0, k, i] - local_width)
                        hi  = min(num_grid_row - 1,
                                  max_indices_row[0, k, i] + local_width) + 1
                        idx = list(range(lo, hi))
                        sm  = self._soft_max(loc_row[0, lo:hi, k, i])
                        x   = (np.sum(sm * idx) + 0.5) / (num_grid_row - 1) * self.original_frame_width
                        y   = row_anchor[k] * self.original_frame_height
                        tmp.append((int(x), int(y)))
            coords.append(tmp)

        for i in col_lane_idx:
            tmp = []
            if np.sum(valid_col[0, :, i]) > num_cls_col / 4:
                for k in range(valid_col.shape[1]):
                    if valid_col[0, k, i]:
                        lo  = max(0, max_indices_col[0, k, i] - local_width)
                        hi  = min(num_grid_col - 1,
                                  max_indices_col[0, k, i] + local_width) + 1
                        # FIX: original built list(range(lo,hi)) then immediately
                        # overwrote it with range(lo,hi), making the list() dead.
                        # Now just uses range directly for the softmax indexing.
                        all_ind = range(lo, hi)
                        sm  = self._soft_max(loc_col[0, lo:hi, k, i])
                        y   = (np.sum(sm * all_ind) + 0.5) / (num_grid_col - 1) * self.original_frame_height
                        x   = col_anchor[k] * self.original_frame_width
                        tmp.append((int(x), int(y)))
            coords.append(tmp)

        return coords

    def get_coordinates(self, endnodes: np.ndarray) -> list:
        """
        Get lane coordinates from inference output.

        Args:
            endnodes: Concatenated inference output tensor.

        Returns:
            List of lanes with (x, y) coordinates.
        """
        loc_row, loc_col, exist_row, exist_col = self._slice_and_reshape(endnodes)
        return self._pred2coords(loc_row, loc_col, exist_row, exist_col)

    def get_original_frame_size(self) -> tuple[int, int]:
        """Return (width, height) of the original frame."""
        return (self.original_frame_width, self.original_frame_height)


# ── Module-level utilities ────────────────────────────────────────────────────

def check_process_errors(*processes) -> None:
    """
    Check exit codes of completed processes; raise if any failed.

    Args:
        processes: Completed multiprocessing.Process instances.

    Raises:
        RuntimeError: If one or more processes exited with a non-zero code.
    """
    failed = False
    for p in processes:
        if p.exitcode != 0:
            logger.error(f"{p.name} exited with code {p.exitcode}")
            failed = True
    if failed:
        raise RuntimeError("One or more processes terminated with an error.")


def configure_output_video(output_path: str,
                           frame_rate: int,
                           resolution: tuple[int, int]) -> cv2.VideoWriter:
    """
    Create a VideoWriter for the given path, frame rate, and resolution.

    Args:
        output_path: Path to the output video file.
        frame_rate: Frames per second.
        resolution: (width, height) of the output video.

    Returns:
        cv2.VideoWriter instance ready to receive frames.
    """
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    return cv2.VideoWriter(output_path, fourcc, frame_rate, resolution)


def compute_scaled_radius(width: int, height: int,
                           standard_width: int = 1280,
                           standard_height: int = 720,
                           base_radius: int = 5) -> int:
    """
    Compute a circle radius scaled to the video resolution.

    Args:
        width: Frame width.
        height: Frame height.
        standard_width: Reference width for scaling.
        standard_height: Reference height for scaling.
        base_radius: Radius at reference resolution.

    Returns:
        Scaled radius (minimum 1).
    """
    scale  = hypot(width, height) / hypot(standard_width, standard_height)
    return max(int(base_radius * scale), 1)
