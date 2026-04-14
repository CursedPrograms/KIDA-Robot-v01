import json
import numpy as np


class PostProcessor:
    """Damoyolo Postprocessor for DeGirum PySDK."""

    def __init__(self, json_config):
        """
        Initialize the Damoyolo postprocessor with configuration settings.

        Parameters:
            json_config (str): JSON string containing post-processing configuration.
        """
        config = json.loads(json_config)

        # Extract input image dimensions from PRE_PROCESS
        pre_process = config["PRE_PROCESS"][0]
        self.image_width = pre_process.get(
            "InputW", 640
        )  # Default to 640 if not provided
        self.image_height = pre_process.get(
            "InputH", 640
        )  # Default to 640 if not provided
        self.input_shape = (self.image_height, self.image_width)

        # Extract post-process configurations
        post_process = config.get("POST_PROCESS", [{}])[0]
        self.strides = np.array(
            post_process.get("Strides", [8, 16, 32]), dtype=np.int32
        )
        self.reg_max = post_process.get("RegMax", 16)  # Default reg_max value
        self.conf_threshold = post_process.get("OutputConfThreshold", 0.3)
        self.nms_iou_thresh = post_process.get("OutputNMSThreshold", 0.6)
        self.num_classes = post_process.get("OutputNumClasses", 80)

        # Load label dictionary (LabelsPath is required in POST_PROCESS)
        label_path = post_process.get("LabelsPath", None)
        if label_path is None:
            raise ValueError("LabelsPath is required in POST_PROCESS configuration.")

        with open(label_path, "r") as json_file:
            self._label_dictionary = json.load(json_file)

        # Prepare priors
        self.mlvl_priors = self._generate_priors()
        project = np.linspace(0, self.reg_max, self.reg_max + 1)
        self.y = project[:, None]  # Shape: (reg_max+1, 1)

    def distance2bbox(self, points, distance, max_shape=None):
        """Decode distance prediction to bounding box."""
        # points: (N, total_num_priors, 2) -> (x_center, y_center)
        # distance: (N, total_num_priors, 4) -> (dx, dy, dw, dh)

        # Calculate the left, top, right, bottom coordinates of the bounding box
        x1 = points[:, :, 0] - distance[:, :, 0]  # x_center - dx
        y1 = points[:, :, 1] - distance[:, :, 1]  # y_center - dy
        x2 = points[:, :, 0] + distance[:, :, 2]  # x_center + dw
        y2 = points[:, :, 1] + distance[:, :, 3]  # y_center + dh

        if max_shape is not None:
            # Clamp values if max_shape is provided (for boundary control)
            x1 = np.clip(x1, 0, max_shape[1])
            y1 = np.clip(y1, 0, max_shape[0])
            x2 = np.clip(x2, 0, max_shape[1])
            y2 = np.clip(y2, 0, max_shape[0])

        # Stack the results into a final bounding box of shape (N, total_num_priors, 4)
        return np.stack([x1, y1, x2, y2], axis=-1)

    def integral(self, x):
        """Integral layer for calculating bounding box locations."""
        x = np.matmul(x, self.y).reshape(1, -1, 4)
        return x

    def get_single_level_center_priors(
        self, batch_size, featmap_size, stride, dtype=np.float32, device=None
    ):
        """
        Generate priors (anchors) for a single level of the feature map.

        Args:
        - batch_size (int): The batch size.
        - featmap_size (tuple): Feature map size as (height, width).
        - stride (int): The stride of the feature map.

        Returns:
        - priors (np.ndarray): Generated priors with shape [batch_size, num_priors, 4].
        """
        h, w = featmap_size
        x_range = np.arange(0, w) * stride
        y_range = np.arange(0, h) * stride

        x = np.tile(x_range, (h, 1))
        y = np.tile(y_range[:, None], (1, w))

        priors = np.stack(
            [
                x.flatten(),
                y.flatten(),
                np.full_like(x.flatten(), stride),
                np.full_like(x.flatten(), stride),
            ],
            axis=-1,
        )

        return np.tile(priors, (batch_size, 1, 1))

    def _generate_priors(self):
        """Generate priors for each feature map level."""
        priors_list = [
            self.get_single_level_center_priors(
                1,
                [self.input_shape[0] // stride, self.input_shape[1] // stride],
                stride,
                dtype=np.float32,
            )
            for stride in self.strides
        ]
        return np.concatenate(priors_list, axis=1)

    def prepare_model_outputs(self, tensor_list, details_list):
        """Prepare model outputs for postprocessing by dequantizing the outputs."""
        cls_scores = []
        bbox_preds = []

        for data, tensor_info in zip(tensor_list, details_list):
            scale, zero_point = tensor_info["quantization"]
            dequantized_data = (data.astype(np.float32) - zero_point) * scale

            # Separate class scores and bounding box predictions based on output shape
            if dequantized_data.shape[-1] == 4 * (
                self.reg_max + 1
            ):  # Bounding box predictions
                bbox_preds.append(dequantized_data)
            else:  # Class scores
                cls_scores.append(dequantized_data)

        return cls_scores, bbox_preds

    def forward(self, tensor_list, details_list):
        """Process model outputs to decode bounding boxes and class scores."""
        cls_scores, bbox_preds = self.prepare_model_outputs(tensor_list, details_list)
        cls_scores_new = []
        bbox_preds_new = []

        for cls_score, bbox_pred in zip(cls_scores, bbox_preds):
            N, HW, C = bbox_pred.shape
            bbox_pred = np.exp(bbox_pred.reshape(N, HW, 4, self.reg_max + 1)) / np.sum(
                np.exp(bbox_pred.reshape(N, HW, 4, self.reg_max + 1)),
                axis=3,
                keepdims=True,
            )
            bbox_pred = bbox_pred.reshape(N, HW * 4, self.reg_max + 1)
            bbox_preds_new.append(bbox_pred)
            cls_score = cls_score.reshape(N, -1, self.num_classes + 1)
            cls_scores_new.append(cls_score)
        new_cls_scores = np.concatenate(cls_scores_new, axis=1)[
            :, :, : self.num_classes
        ]  # Keep only num_classes
        new_bbox_preds = np.concatenate(bbox_preds_new, axis=1)
        new_bbox_preds = self.integral(new_bbox_preds)
        new_bbox_preds = new_bbox_preds * self.mlvl_priors[..., 2, None]
        decoded_boxes = self.distance2bbox(
            self.mlvl_priors[..., :2], new_bbox_preds, max_shape=self.input_shape
        )

        # Apply NMS and return the final bounding boxes, scores, and class indices
        selected_bboxes, selected_scores, selected_class_indices = self.apply_nms(
            decoded_boxes, new_cls_scores
        )
        results = []
        for box, score, cls in zip(
            selected_bboxes, selected_scores, selected_class_indices
        ):
            class_id = int(cls)
            label = self._label_dictionary.get(str(class_id), f"class_{class_id}")
            results.append(
                {
                    "bbox": box.tolist(),
                    "category_id": class_id,
                    "label": label,
                    "score": float(score),
                }
            )
        return results

    def compute_iou(self, box, boxes):
        """
        Compute the Intersection over Union (IoU) between a single bounding box and a list of boxes.

        Args:
        - box (np.ndarray): A single bounding box, shape [4].
        - boxes (np.ndarray): List of bounding boxes, shape [num_boxes, 4].

        Returns:
        - iou (np.ndarray): Array of IoU values between the box and the list of boxes.
        """
        # Calculate intersection
        x1 = np.maximum(box[0], boxes[:, 0])
        y1 = np.maximum(box[1], boxes[:, 1])
        x2 = np.minimum(box[2], boxes[:, 2])
        y2 = np.minimum(box[3], boxes[:, 3])

        # Calculate the area of the intersection
        inter_area = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)

        # Calculate the area of both boxes
        box_area = (box[2] - box[0]) * (box[3] - box[1])
        boxes_area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])

        # Calculate IoU
        iou = inter_area / (box_area + boxes_area - inter_area)

        return iou

    def nms_per_class(self, bboxes, scores):
        """
        Apply NMS per class to handle bounding boxes separately for each class.

        Args:
        - bboxes (np.ndarray): Bounding boxes for each class, shape [num_boxes, 4].
        - scores (np.ndarray): Confidence scores for each bounding box, shape [num_boxes].
        - iou_threshold (float): IoU threshold for NMS.

        Returns:
        - selected_bboxes (np.ndarray): Bounding boxes after NMS.
        - selected_scores (np.ndarray): Confidence scores after NMS.
        - selected_class_indices (np.ndarray): Class indices for each bounding box.
        """
        # Sort the bounding boxes by their confidence scores in descending order
        indices = np.argsort(scores)[::-1]

        # List to hold the selected boxes, their scores, and class indices
        selected_bboxes = []
        selected_scores = []
        selected_class_indices = []

        while len(indices) > 0:
            # Get the current box with the highest score
            current = indices[0]
            selected_bboxes.append(bboxes[current])
            selected_scores.append(scores[current])
            selected_class_indices.append(
                np.full_like(current, -1)
            )  # Initially, class index placeholder

            if len(indices) == 1:
                break

            # Compute IoU for the remaining boxes with the current box
            remaining_boxes = bboxes[indices[1:]]
            iou = self.compute_iou(bboxes[current], remaining_boxes)

            # Keep boxes whose IoU is less than the threshold
            indices = indices[1:][iou < self.nms_iou_thresh]

        return (
            np.array(selected_bboxes),
            np.array(selected_scores),
            np.array(selected_class_indices),
        )

    def apply_nms(self, bboxes, scores):
        """
        Apply NMS for multiple classes by handling each class independently.

        Args:
        - bboxes (np.ndarray): Bounding boxes, shape [1, num_boxes, 4].
        - scores (np.ndarray): Confidence scores, shape [1, num_boxes, num_classes].

        Returns:
        - final_bboxes (np.ndarray): Bounding boxes after NMS for each class.
        - final_scores (np.ndarray): Scores after NMS for each class.
        - final_class_indices (np.ndarray): Class indices after NMS for each bounding box.
        """
        final_bboxes = []
        final_scores = []
        final_class_indices = []

        # Extract the batch dimension (assuming batch size is 1)
        bboxes = bboxes[0]  # Shape: [num_boxes, 4]
        scores = scores[0]  # Shape: [num_boxes, num_classes]

        # Process each class independently
        for class_idx in range(self.num_classes):
            # Select the boxes and scores for the current class
            class_mask = (
                scores[:, class_idx] > self.conf_threshold
            )  # Filter based on confidence threshold
            class_bboxes = bboxes[class_mask]
            class_scores = scores[class_mask, class_idx]

            # Apply NMS for the current class
            if (
                class_bboxes.size > 0
            ):  # Check if there are any valid bounding boxes for this class
                selected_bboxes, selected_scores, selected_class_indices_ = (
                    self.nms_per_class(class_bboxes, class_scores)
                )
                if selected_bboxes.size > 0:  # Check if any boxes survived NMS
                    final_bboxes.append(selected_bboxes)
                    final_scores.append(selected_scores)
                    final_class_indices.append(
                        np.full_like(selected_class_indices_, class_idx)
                    )

        # Ensure that final_bboxes, final_scores, and final_class_indices are consistent
        if final_bboxes:  # Check if there are any results for the classes
            final_bboxes = np.concatenate(final_bboxes, axis=0)
            final_scores = np.concatenate(final_scores, axis=0)
            final_class_indices = np.concatenate(final_class_indices, axis=0)
        else:
            # If no boxes survived NMS, return empty arrays
            final_bboxes = np.empty((0, 4))
            final_scores = np.empty((0,))
            final_class_indices = np.empty((0,))

        return final_bboxes, final_scores, final_class_indices
