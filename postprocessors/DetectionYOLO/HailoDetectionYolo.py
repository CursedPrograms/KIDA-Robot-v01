import numpy as np
import json


# Post-processor class, must have fixed name 'PostProcessor'
class PostProcessor:
    def __init__(self, json_config):
        """
        Initialize the post-processor with configuration settings.

        Parameters:
            json_config (str): JSON string containing post-processing configuration.
        """
        # Parse the JSON configuration
        self._json_config = json.loads(json_config)

        # Extract configuration parameters
        self._num_classes = int(
            self._json_config["POST_PROCESS"][0]["OutputNumClasses"]
        )
        self._label_json_path = self._json_config["POST_PROCESS"][0]["LabelsPath"]
        self._input_height = int(self._json_config["PRE_PROCESS"][0]["InputH"])
        self._input_width = int(self._json_config["PRE_PROCESS"][0]["InputW"])

        # Load label dictionary from JSON file
        with open(self._label_json_path, "r") as json_file:
            self._label_dictionary = json.load(json_file)

        # Extract confidence threshold
        self._output_conf_threshold = float(
            self._json_config["POST_PROCESS"][0].get("OutputConfThreshold", 0.0)
        )

    def forward(self, tensor_list, details_list):
        """
        Process the raw output tensor to produce formatted JSON results.

        Parameters:
            tensor_list (list): List of tensors from the model.
            details_list (list): Additional details (unused in this example).

        Returns:
            str: JSON-formatted string containing detection results.
        """
        # Initialize results list
        new_inference_results = []

        # Extract and reshape the raw output tensor
        output_array = tensor_list[0].reshape(-1)

        # Index to parse the array
        index = 0

        # Iterate over classes and parse results
        for class_id in range(self._num_classes):
            # Number of detections for this class
            num_detections = int(output_array[index])
            index += 1  # Move to the next entry

            # Skip if no detections for this class
            if num_detections == 0:
                continue

            # Process each detection for this class
            for _ in range(num_detections):
                if index + 5 > len(output_array):
                    # Safeguard against unexpected array end
                    break

                # Extract score and bounding box in x_center, y_center, width, height format
                score = float(output_array[index + 4])
                y_min, x_min, y_max, x_max = map(float, output_array[index : index + 4])
                index += 5  # Move to the next detection

                # Skip detections below the confidence threshold
                if score < self._output_conf_threshold:
                    continue

                # Convert to x_min, y_min, x_max, y_max format
                x_min = x_min * self._input_width
                y_min = y_min * self._input_height
                x_max = x_max * self._input_width
                y_max = y_max * self._input_height

                # Format the detection result
                result = {
                    "bbox": [x_min, y_min, x_max, y_max],
                    "score": score,
                    "category_id": class_id,
                    "label": self._label_dictionary.get(
                        str(class_id), f"class_{class_id}"
                    ),
                }
                new_inference_results.append(result)

            # Stop processing if padded zeros are reached
            if index >= len(output_array) or all(v == 0 for v in output_array[index:]):
                break

        # Return results as JSON string
        return json.dumps(new_inference_results)
