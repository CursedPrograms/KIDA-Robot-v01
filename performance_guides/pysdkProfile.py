# Profile performance of a model using DeGirum PySDK
import degirum as dg
import degirum_tools

iterations = 2500 # Number of iterations to run with the model

# For testing the local hardware:
hw_location = "@local"
# For testing inference on an AIServer running locally or on your LAN, uncomment:
# hw_location = "localhost" or AIServer IP

# For testing a model file from the DeGirum AI Hub:
# Any model from https://hub.degirum.com/degirum/hailo
model_name = "yolov8n_relu6_face--640x640_quant_hailort_hailo8_1"

# Load the model
model = dg.load_model(
    model_name=model_name,
    inference_host_address=hw_location,
    zoo_url="https://hub.degirum.com/degirum/hailo",
)

# If instead, you want to test a local model file, say:
# model_name = "local_model_name"
# You must ensure that the model .hef file is adjacent to its corresponding model parameter JSON file.
# For information on PySDK model parameter JSON file formats, look at examples for similar models in the DeGirum AI Hub
# or refer to: https://docs.degirum.com/pysdk/user-guide-pysdk/model-json-structure

# Specify zoo_url parameter as either a path to a local model zoo directory
# or a direct path to a model's .json configuration file.
# model = dg.load_model(
#     model_name=model_name,
#     inference_host_address="@local",
#     zoo_url="path/to/your/model_name.json",
# )

# Set the model's thread pack size for maximum performance
model._model_parameters.ThreadPackSize = 6

# Turn off C++-based post-processing (Does not affect models with a 'PythonFile' python-based postprocessor!)
model.output_postprocess_type = "None"

results = degirum_tools.model_time_profile(model, iterations)
print(f"Observed FPS: {results.observed_fps:5.2f}")
