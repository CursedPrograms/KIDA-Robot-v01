#!/bin/bash
# Script to test parallel inference on multiple models across multiple processes.
# Uses 3 processes.
# We achieve multi-process support by either using an AIServer or by enabling Hailo's multi-process service.

# Host Address:
# Use '@local' for local hardware inference without an AIServer. NEEDS hailo multi-process service to be running.
# Use 'localhost' for local hardware inference on a running AIServer. Does NOT need hailo multi-process service to be running.
HOST_ADDRESS='@local'
# HOST_ADDRESS='localhost'

# List of models to test (you can use any models from https://hub.degirum.com/degirum/hailo)
MODEL_NAMES=(
    "yolov8n_relu6_face--640x640_quant_hailort_hailo8_1"
    "yolov8n_relu6_car--640x640_quant_hailort_hailo8_1"
    "yolov8n_relu6_hand--640x640_quant_hailort_hailo8_1"
)
ITERATIONS=2500

for i in {0..2}; do
    echo "Starting process $((i+1)) with model ${MODEL_NAMES[i]}..."
    python -c "import degirum as dg; \
    from degirum_tools import model_time_profile; \
    model = dg.load_model(model_name='${MODEL_NAMES[i]}', inference_host_address='$HOST_ADDRESS', zoo_url='https://hub.degirum.com/degirum/hailo'); \
    model._model_parameters.ThreadPackSize = 6; \
    fps = model_time_profile(model, $ITERATIONS).observed_fps; \
    print('Process $((i+1)), Observed FPS: {:.2f}'.format(fps))" &
done

wait
echo "All processes completed."

