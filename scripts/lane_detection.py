#!/usr/bin/env python3
# lane_detection.py — UFLD v2 lane detection on Hailo accelerator
#
# Fixes vs original:
#   • total_frames was referenced inside postprocess_output() but never
#     passed in — it was only available in __main__ scope.  It is now a
#     parameter of postprocess_output() (and threaded through infer()).
#   • get_video_info() ValueError was caught in __main__ but execution
#     continued past it, passing uninitialised variables to UFLDProcessing.
#     sys.exit(1) is now called on failure.
#   • On inference error, input_queue.put(None) is called before terminating
#     so the preprocess Process doesn't hang waiting for queue space.
#   • Typo "infernce callback" → "inference callback" in docstring.

import multiprocessing as mp
import argparse
import sys
import os
from multiprocessing import Process
from functools import partial

import numpy as np
from loguru import logger
import cv2

from lane_detection_utils import (UFLDProcessing,
                                  check_process_errors,
                                  compute_scaled_radius)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.hailo_inference import HailoAsyncInference


def parser_init() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(description="UFLD_v2 inference")
    parser.add_argument("-n", "--net",
                        default="ufld_v2_tu.hef",
                        help="Path to HEF model file.")
    parser.add_argument("-i", "--input_video",
                        default="input_video.mp4",
                        help="Path of the input video.")
    parser.add_argument("-o", "--output_video",
                        default="output_video.mp4",
                        help="Path for the output video.")
    return parser


def get_video_info(video_path: str) -> tuple[int, int, int]:
    """
    Return (frame_width, frame_height, frame_count) for a video file.

    Raises:
        ValueError: If the file cannot be opened.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"Cannot open video file: {video_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return w, h, n


def preprocess_input(video_path: str,
                     input_queue: mp.Queue,
                     width: int, height: int,
                     ufld_processing: UFLDProcessing) -> None:
    """
    Read video frames, preprocess, and push to input_queue.
    Puts None as sentinel when done.
    """
    cap     = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    while ok:
        resized = ufld_processing.resize(frame, height, width)
        input_queue.put(([frame], [resized]))
        ok, frame = cap.read()
    cap.release()
    input_queue.put(None)


def postprocess_output(output_queue: mp.Queue,
                       output_video_path: str,
                       ufld_processing: UFLDProcessing,
                       total_frames: int) -> None:
    """
    Consume inference results from output_queue, draw lane points, write video.

    Args:
        output_queue: Queue of (original_frame, inference_output) tuples.
        output_video_path: Destination file path.
        ufld_processing: Lane-detection post-processing instance.
        total_frames: Expected frame count (used for the progress bar).
    """
    # Import tqdm here to avoid multiprocessing pickling issues
    from tqdm import tqdm

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    width, height = ufld_processing.get_original_frame_size()
    writer = cv2.VideoWriter(output_video_path, fourcc, 20, (width, height))
    radius = compute_scaled_radius(width, height)

    with tqdm(total=total_frames, desc="Processing frames") as pbar:
        while True:
            result = output_queue.get()
            if result is None:
                break
            original_frame, inference_output = result
            slices = [
                inference_output['ufld_v2_tu/slice1'],
                inference_output['ufld_v2_tu/slice2'],
                inference_output['ufld_v2_tu/slice3'],
                inference_output['ufld_v2_tu/slice4'],
            ]
            output_tensor = np.concatenate(slices, axis=1)
            lanes = ufld_processing.get_coordinates(output_tensor)

            for lane in lanes:
                for coord in lane:
                    cv2.circle(original_frame, coord, radius, (0, 255, 0), -1)
            writer.write(original_frame.astype('uint8'))
            pbar.update(1)

    writer.release()


def inference_callback(completion_info,
                       bindings_list: list,
                       input_batch: list,
                       output_queue: mp.Queue) -> None:
    """
    Inference callback: push results to output_queue.

    Args:
        completion_info: Hailo inference completion info.
        bindings_list: Output bindings for each inference item.
        input_batch: Original input frames matching bindings_list.
        output_queue: Queue to push (frame, result) tuples to.
    """
    if completion_info.exception:
        logger.error(f"Inference error: {completion_info.exception}")
        return
    for i, bindings in enumerate(bindings_list):
        if len(bindings._output_names) == 1:
            result = bindings.output().get_buffer()
        else:
            result = {
                name: np.expand_dims(bindings.output(name).get_buffer(), axis=0)
                for name in bindings._output_names
            }
        output_queue.put((input_batch[i], result))


def infer(video_path: str,
          net_path: str,
          batch_size: int,
          output_video_path: str,
          ufld_processing: UFLDProcessing) -> None:
    """
    Run the full lane-detection pipeline:
      preprocess → Hailo async inference → postprocess → write video.

    Args:
        video_path: Input video path.
        net_path: HEF model file path.
        batch_size: Frames per inference batch.
        output_video_path: Output video path.
        ufld_processing: UFLDProcessing instance (carries total_frames).
    """
    input_queue  = mp.Queue()
    output_queue = mp.Queue()
    callback_fn  = partial(inference_callback, output_queue=output_queue)

    hailo_inference = HailoAsyncInference(
        net_path, input_queue, callback_fn, batch_size,
        output_type="FLOAT32", send_original_frame=True,
    )
    h, w, _ = hailo_inference.get_input_shape()

    preprocess  = Process(target=preprocess_input,
                          args=(video_path, input_queue, w, h, ufld_processing))
    # FIX: total_frames is now passed explicitly instead of relying on the
    # __main__ global which is invisible inside the child process.
    postprocess = Process(target=postprocess_output,
                          args=(output_queue, output_video_path,
                                ufld_processing, ufld_processing.total_frames))

    preprocess.start()
    postprocess.start()

    try:
        hailo_inference.run()
        preprocess.join()
        output_queue.put(None)   # sentinel → postprocess exits cleanly
        postprocess.join()
        check_process_errors(preprocess, postprocess)
        logger.info(f"Done. Results saved to {output_video_path}")

    except Exception as e:
        logger.error(f"Inference pipeline error: {e}")
        # FIX: flush input_queue so preprocess doesn't block on a full queue
        # before we terminate it.
        try:
            input_queue.put(None)
        except Exception:
            pass
        input_queue.close()
        output_queue.close()
        preprocess.terminate()
        postprocess.terminate()
        os._exit(1)


if __name__ == "__main__":
    args = parser_init().parse_args()

    # FIX: sys.exit on failure instead of continuing with uninitialised vars
    try:
        frame_width, frame_height, total_frames = get_video_info(args.input_video)
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    ufld_processing = UFLDProcessing(
        num_cell_row=100,
        num_cell_col=100,
        num_row=56,
        num_col=41,
        num_lanes=4,
        crop_ratio=0.8,
        original_frame_width=frame_width,
        original_frame_height=frame_height,
        total_frames=total_frames,
    )

    infer(
        args.input_video,
        args.net,
        batch_size=1,
        output_video_path=args.output_video,
        ufld_processing=ufld_processing,
    )
