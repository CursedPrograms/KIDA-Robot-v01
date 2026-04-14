import numpy as np
import json


class PostProcessor:
    """SCRFD Postprocessor for DeGirum PySDK."""

    def __init__(self, json_config):
        """
        Initialize the post-processor with configuration settings.

        Parameters:
            json_config (str): JSON string containing post-processing configuration.
        """
        config = json.loads(json_config)

        # Extract input image dimensions
        pre_process = config["PRE_PROCESS"][0]
        self.image_width = pre_process.get("InputW", 640)
        self.image_height = pre_process.get("InputH", 640)

        # Extract post-process configurations
        post_process = config.get("POST_PROCESS", [{}])[0]
        self.strides = post_process.get("Strides", [8, 16, 32])
        anchor_config = post_process.get("AnchorConfig", {})
        self.min_sizes = anchor_config.get(
            "MinSizes", [[16, 32], [64, 128], [256, 512]]
        )
        self.steps = anchor_config.get("Steps", [8, 16, 32])
        self.nms_iou_thresh = post_process.get("OutputNMSThreshold", 0.4)
        self.score_threshold = post_process.get("OutputConfThreshold", 0.5)
        self.num_classes = 1  # Fixed for SCRFD
        self.num_landmarks = 10  # Fixed for SCRFD
        self.num_branches = len(self.strides)

        # Load label dictionary
        label_path = post_process.get("LabelsPath", None)
        if label_path is None:
            raise ValueError("LabelsPath is required in POST_PROCESS configuration.")
        with open(label_path, "r") as json_file:
            self._label_dictionary = json.load(json_file)

        # Generate anchors dynamically
        self.anchors = self._generate_anchors(self.min_sizes, self.steps)

    def _generate_anchors(self, min_sizes, steps):
        """Generate anchor boxes for detection."""
        anchors = []
        for stride, min_size in zip(steps, min_sizes):
            height, width = self.image_height // stride, self.image_width // stride
            num_anchors = len(min_size)

            centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(
                np.float32
            )
            centers = (centers * stride).reshape((-1, 2))
            centers[:, 0] /= self.image_width
            centers[:, 1] /= self.image_height

            if num_anchors > 1:
                centers = np.stack([centers] * num_anchors, axis=1).reshape((-1, 2))
            scales = np.ones_like(centers, dtype=np.float32) * stride
            scales[:, 0] /= self.image_width
            scales[:, 1] /= self.image_height
            anchors.append(np.concatenate([centers, scales], axis=1))
        return np.concatenate(anchors, axis=0)

    def forward(self, tensor_list, details_list):
        """
        Perform postprocessing on raw model outputs.

        Parameters:
            tensor_list (list): List of tensors from the model.
            details_list (list): Additional metadata for the tensors.

        Returns:
            str: JSON string containing processed inference results.
        """
        # Step 1: Dequantize tensors
        dequantized_tensors = []
        for data, tensor_info in zip(tensor_list, details_list):
            quantization = tensor_info["quantization"]
            scale, zero_point = quantization[0], quantization[1]
            dequantized_data = (data.astype(np.float32) - zero_point) * scale
            dequantized_tensors.append(dequantized_data)

        # Step 2: Collect predictions for boxes, classes, and landmarks
        box_preds, class_preds, landmark_preds = self._collect_predictions(
            dequantized_tensors
        )

        # Step 3: Decode bounding boxes and reshape to batch dimensions
        batch_size = box_preds.shape[
            0
        ]  # Get the batch size from the first dimension of predictions
        decoded_boxes = self._decode_boxes(box_preds.reshape(-1, 4), self.anchors)
        detection_boxes = decoded_boxes.reshape(
            batch_size, -1, 4
        )  # Restore batch dimension

        # Step 4: Decode landmarks (if available) and reshape to batch dimensions
        if landmark_preds is not None:
            decoded_landmarks = self._decode_landmarks(
                landmark_preds.reshape(-1, self.num_landmarks), self.anchors
            )
            detection_landmarks = decoded_landmarks.reshape(
                batch_size, -1, self.num_landmarks
            )
        else:
            detection_landmarks = None

        # Step 5: Process each batch independently
        new_inference_results = []
        for batch_idx in range(batch_size):
            boxes = detection_boxes[batch_idx]
            scores = class_preds[batch_idx].squeeze(-1)
            landmarks = (
                detection_landmarks[batch_idx]
                if detection_landmarks is not None
                else None
            )

            # Filter by score threshold
            mask = scores >= self.score_threshold
            filtered_boxes = boxes[mask]
            filtered_scores = scores[mask]
            filtered_landmarks = landmarks[mask] if landmarks is not None else None

            # Apply Non-Maximum Suppression
            keep_indices = self._apply_non_max_suppression(
                filtered_boxes, filtered_scores
            )
            final_boxes = filtered_boxes[keep_indices]
            final_scores = filtered_scores[keep_indices]
            final_landmarks = (
                filtered_landmarks[keep_indices]
                if filtered_landmarks is not None
                else None
            )

            # Prepare results for this batch
            for i in range(len(final_boxes)):
                category_id = 0  # Assuming single class for SCRFD
                label = self._label_dictionary.get(
                    str(category_id), f"class_{category_id}"
                )
                result = {
                    "bbox": final_boxes[
                        i
                    ].tolist(),  # Keep bbox as a list, not flattened
                    "category_id": category_id,
                    "label": label,
                    "score": float(final_scores[i]),
                    "landmarks": [],
                }

                # Add landmarks in the desired format
                if final_landmarks is not None:
                    for landmark_idx in range(0, len(final_landmarks[i]), 2):
                        landmark_entry = {
                            "category_id": landmark_idx // 2,
                            "connect": [],
                            "landmark": [
                                float(final_landmarks[i][landmark_idx]),
                                float(final_landmarks[i][landmark_idx + 1]),
                            ],
                            "score": float(
                                final_scores[i]
                            ),  # Optionally assign the detection score
                        }
                        result["landmarks"].append(landmark_entry)

                new_inference_results.append(result)

        return new_inference_results

    def _collect_predictions(self, outputs):
        """Collect predictions for boxes, classes, and optionally landmarks."""
        box_preds, class_preds, landmark_preds = [], [], []
        num_outputs = len(outputs)

        # Infer presence of landmarks based on the number of outputs
        include_landmarks = (num_outputs // self.num_branches) > 2

        for i in range(0, num_outputs, self.num_branches):
            batch_size = outputs[i].shape[0]
            box_preds.append(outputs[i].reshape(batch_size, -1, 4))
            class_preds.append(outputs[i + 1].reshape(batch_size, -1, self.num_classes))

            if include_landmarks:
                landmark_preds.append(
                    outputs[i + 2].reshape(batch_size, -1, self.num_landmarks)
                )

        box_preds = np.concatenate(box_preds, axis=1)
        class_preds = np.concatenate(class_preds, axis=1)
        landmark_preds = (
            np.concatenate(landmark_preds, axis=1) if include_landmarks else None
        )

        return box_preds, class_preds, landmark_preds

    def _decode_boxes(self, box_detections, anchors):
        """Decode bounding boxes using anchor offsets and scale to image size."""
        x1 = anchors[:, 0] - box_detections[:, 0] * anchors[:, 2]
        y1 = anchors[:, 1] - box_detections[:, 1] * anchors[:, 3]
        x2 = anchors[:, 0] + box_detections[:, 2] * anchors[:, 2]
        y2 = anchors[:, 1] + box_detections[:, 3] * anchors[:, 3]

        # Scale to image size
        x1 *= self.image_width
        y1 *= self.image_height
        x2 *= self.image_width
        y2 *= self.image_height

        return np.stack([x1, y1, x2, y2], axis=-1)

    def _decode_landmarks(self, landmark_detections, anchors):
        """Decode facial landmarks using anchor offsets and scale to image size."""
        predictions = []
        for i in range(0, self.num_landmarks, 2):
            px = anchors[:, 0] + landmark_detections[:, i] * anchors[:, 2]
            py = anchors[:, 1] + landmark_detections[:, i + 1] * anchors[:, 3]

            # Scale to image size
            px *= self.image_width
            py *= self.image_height

            predictions.extend([px, py])
        return np.stack(predictions, axis=-1)

    def _apply_non_max_suppression(self, boxes, scores):
        """Apply Non-Maximum Suppression (NMS) to remove redundant detections."""
        if len(boxes) == 0:
            return []

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

            inter_area = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            union_area = areas[i] + areas[order[1:]] - inter_area
            iou = inter_area / union_area

            order = order[1:][iou <= self.nms_iou_thresh]

        return keep
