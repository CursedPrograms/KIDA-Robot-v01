import numpy as np
import json


class PostProcessor:
    def __init__(self, json_config):
        """
        Initialize RetinaFace postprocessor from a JSON configuration.
        Args:
            json_config (dict): JSON configuration dictionary.
        """
        config = json.loads(json_config)
        # Parse configuration
        post_process_config = config["POST_PROCESS"][0]
        anchor_config = post_process_config["AnchorConfig"]
        pre_process_config = config["PRE_PROCESS"][0]

        # Input dimensions
        self.input_size = (pre_process_config["InputH"], pre_process_config["InputW"])

        # Anchor configuration
        self.cfg = {
            "min_sizes": anchor_config["MinSizes"],
            "steps": anchor_config["Steps"],
            "variance": [0.1, 0.2],  # Default variance for RetinaFace models
        }

        # Thresholds
        self.confidence_threshold = post_process_config.get("OutputConfThreshold", 0.5)
        self.nms_threshold = post_process_config.get("OutputNMSThreshold", 0.4)

        # Load label dictionary
        label_path = post_process_config.get("LabelsPath", None)
        if label_path is None:
            raise ValueError("LabelsPath is required in POST_PROCESS configuration.")
        with open(label_path, "r") as json_file:
            self._label_dictionary = json.load(json_file)

        # Generate priors and anchor info
        self.priors = self._generate_priors()
        self.anchor_info = self._generate_anchor_info()

    def _generate_anchor_info(self):
        """
        Generate anchor information for each feature map.
        Returns:
            List of dictionaries containing expected last dimension and output type.
        """
        anchor_info = []
        for step, min_sizes in zip(self.cfg["steps"], self.cfg["min_sizes"]):
            feature_map_width = self.input_size[1] // step
            feature_map_height = self.input_size[0] // step
            num_anchors = feature_map_width * feature_map_height * len(min_sizes)

            anchor_info.extend(
                [
                    {
                        "num_anchors": num_anchors,
                        "last_dim": 4 * len(min_sizes),
                        "type": "bbox",
                    },
                    {
                        "num_anchors": num_anchors,
                        "last_dim": 2 * len(min_sizes),
                        "type": "conf",
                    },
                    {
                        "num_anchors": num_anchors,
                        "last_dim": 10 * len(min_sizes),
                        "type": "landmark",
                    },
                ]
            )
        return anchor_info

    def _generate_priors(self):
        """
        Generate prior boxes (anchors) for all feature maps.

        Returns:
            np.ndarray: Array of priors with shape (num_priors, 4).
        """
        feature_maps = [
            [self.input_size[0] // step, self.input_size[1] // step]
            for step in self.cfg["steps"]
        ]
        anchors = []

        for k in range(len(feature_maps)):
            f_height, f_width = feature_maps[k]
            step = self.cfg["steps"][k]
            min_sizes = self.cfg["min_sizes"][k]

            for i in range(f_height):  # Loop over feature map rows
                for j in range(f_width):  # Loop over feature map columns
                    for min_size in min_sizes:  # Loop over anchor sizes
                        # Calculate center coordinates and box scales
                        cx = (j + 0.5) * step / self.input_size[1]
                        cy = (i + 0.5) * step / self.input_size[0]
                        s_kx = min_size / self.input_size[1]
                        s_ky = min_size / self.input_size[0]

                        anchors.append([cx, cy, s_kx, s_ky])

        priors = np.array(anchors, dtype=np.float32)
        return priors

    def _dequantize(self, tensor_list, details):
        """
        Dequantize uint8 tensors and dynamically deduce their type based on configuration.
        Args:
            tensor_list (list): List of uint8 output tensors.
            details (list): List of dictionaries containing quantization info.
        Returns:
            loc (np.ndarray): Dequantized bounding boxes.
            conf (np.ndarray): Dequantized confidence scores.
            landms (np.ndarray): Dequantized landmarks.
        """
        loc_list, conf_list, landms_list = [], [], []

        for tensor, detail, anchor_meta in zip(tensor_list, details, self.anchor_info):
            scale, zero = detail["quantization"]
            dequantized = (tensor.astype(np.float32) - zero) * scale
            expected_last_dim = anchor_meta["last_dim"]
            output_type = anchor_meta["type"]

            # Validate tensor shape compatibility
            if tensor.shape[-1] != expected_last_dim:
                raise ValueError(
                    f"Unexpected last dimension: {tensor.shape[-1]}. Expected {expected_last_dim}."
                )

            # Append to the correct list based on output type
            if output_type == "bbox":
                loc_list.append(dequantized.reshape(-1, 4))
            elif output_type == "conf":
                conf_list.append(dequantized.reshape(-1, 2))
            elif output_type == "landmark":
                landms_list.append(dequantized.reshape(-1, 10))

        loc = np.concatenate(loc_list, axis=0)
        conf = np.concatenate(conf_list, axis=0)
        landms = np.concatenate(landms_list, axis=0)

        return loc, conf, landms

    def decode(self, loc, priors, variances):
        boxes = np.concatenate(
            (
                priors[:, :2] + loc[:, :2] * variances[0] * priors[:, 2:],
                priors[:, 2:] * np.exp(loc[:, 2:] * variances[1]),
            ),
            axis=1,
        )
        boxes[:, :2] -= boxes[:, 2:] / 2
        boxes[:, 2:] += boxes[:, :2]
        return boxes

    def decode_landmarks(self, landms, priors, variances):
        landmarks = np.concatenate(
            [
                priors[:, :2] + landms[:, i : i + 2] * variances[0] * priors[:, 2:]
                for i in range(0, 10, 2)
            ],
            axis=1,
        )
        return landmarks

    def softmax(self, logits):
        exp_logits = np.exp(logits - np.max(logits, axis=1, keepdims=True))
        return exp_logits / np.sum(exp_logits, axis=1, keepdims=True)

    def nms(self, boxes, scores, threshold):
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter)

            inds = np.where(iou <= threshold)[0]
            order = order[inds + 1]
        return keep

    def forward(self, tensor_list, details_list):
        """
        Process RetinaFace model outputs and return detections.
        Args:
            tensor_list (list): List of 9 uint8 output tensors.
            details (list): List of dictionaries containing quantization info.
        Returns:
            boxes (np.ndarray): Final bounding boxes of shape (N, 4).
            scores (np.ndarray): Final confidence scores of shape (N,).
            landmarks (np.ndarray): Final landmarks of shape (N, 10).
        """
        # Dequantize and split outputs
        loc, conf, landms = self._dequantize(tensor_list, details_list)
        variances = self.cfg["variance"]

        # Decode bounding boxes and landmarks
        boxes = self.decode(loc, self.priors, variances)
        boxes[:, ::2] *= self.input_size[1]  # Scale to image width
        boxes[:, 1::2] *= self.input_size[0]  # Scale to image height

        landmarks = self.decode_landmarks(landms, self.priors, variances)
        landmarks[:, ::2] *= self.input_size[1]  # Scale to image width
        landmarks[:, 1::2] *= self.input_size[0]  # Scale to image height

        # Apply softmax to confidence scores
        probs = self.softmax(conf)
        scores = probs[:, 1]  # Face confidence scores

        # Filter low-confidence detections
        inds = np.where(scores > self.confidence_threshold)[0]
        boxes = boxes[inds]
        landmarks = landmarks[inds]
        scores = scores[inds]

        # Apply NMS
        keep = self.nms(boxes, scores, self.nms_threshold)
        boxes = boxes[keep]
        scores = scores[keep]
        landmarks = landmarks[keep]

        new_inference_results = []
        # Prepare results for this batch
        for i in range(len(boxes)):
            category_id = 1  # Assuming single class for SCRFD
            label = self._label_dictionary.get(str(category_id), f"class_{category_id}")
            result = {
                "bbox": boxes[i].tolist(),  # Keep bbox as a list, not flattened
                "category_id": category_id,
                "label": label,
                "score": float(scores[i]),
                "landmarks": [],
            }

            # Add landmarks in the desired format
            if landmarks is not None:
                for landmark_idx in range(0, len(landmarks[i]), 2):
                    landmark_entry = {
                        "category_id": landmark_idx // 2,
                        "connect": [],
                        "landmark": [
                            float(landmarks[i][landmark_idx]),
                            float(landmarks[i][landmark_idx + 1]),
                        ],
                        "score": float(
                            scores[i]
                        ),  # Optionally assign the detection score
                    }
                    result["landmarks"].append(landmark_entry)

            new_inference_results.append(result)

        return new_inference_results
