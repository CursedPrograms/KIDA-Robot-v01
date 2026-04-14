# Script to test parallel inference on multiple models within one process.
# Uses 3 threads.

import threading
import degirum as dg
from degirum_tools import model_time_profile

# Host Address:
# Since we are NOT running in multiple processes, hailo multi-process service does NOT need to running.
# Use '@local' for local hardware inference without an AIServer.
# Use 'localhost' for local hardware inference on a running AIServer.
HOST_ADDRESS = '@local'
# HOST_ADDRESS = 'localhost'

# List of models to test (you can use any models from https://hub.degirum.com/degirum/hailo)
MODEL_NAMES = [
    "yolov8n_relu6_face--640x640_quant_hailort_hailo8_1",
    "yolov8n_relu6_car--640x640_quant_hailort_hailo8_1",
    "yolov8n_relu6_hand--640x640_quant_hailort_hailo8_1"
]
ITERATIONS = 2500

def run_benchmark(thread_id, model):
    print(f"Starting thread {thread_id} on {MODEL_NAMES[thread_id-1]}")
    model._model_parameters.ThreadPackSize = 6
    fps = model_time_profile(model, ITERATIONS).observed_fps
    print(f"Model: {MODEL_NAMES[thread_id-1]} Observed FPS: {fps:.2f}")

# Load all of the models
models = []
for model_name in MODEL_NAMES:
    model = dg.load_model(
        model_name=model_name,
        inference_host_address=HOST_ADDRESS,
        zoo_url="https://hub.degirum.com/degirum/hailo"
    )
    models.append(model)

threads = []
for i in range(1, 4):
    t = threading.Thread(target=run_benchmark, args=(i, models[i-1]))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

print("All threads completed.")
