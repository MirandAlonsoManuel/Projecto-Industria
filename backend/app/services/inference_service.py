from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

import cv2
import numpy as np

from app.services.image_service import map_bbox, map_polygon
from app.services.model_registry import ModelRegistry, ModelRegistryError


class InferenceError(RuntimeError):
    pass


class InferenceService:
    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()
        self._loaded: dict[str, Any] = {}
        self._lock = RLock()

    def _resolve(self, task: str, model_id: str | None) -> dict[str, Any]:
        model = self.registry.get(model_id) if model_id else self.registry.default_for(task)
        if model.get("task") != task:
            raise InferenceError(f"El modelo {model['id']} no corresponde a la tarea {task}.")
        return model

    def _load_model(self, spec: dict[str, Any]) -> Any:
        model_id = spec["id"]
        with self._lock:
            if model_id in self._loaded:
                return self._loaded[model_id]
            backend = spec["backend"]
            config = spec.get("config", {})
            try:
                if backend == "ultralytics":
                    from ultralytics import YOLO

                    model = YOLO(config["weights"])
                elif backend == "torchvision":
                    model = self._load_torchvision(config)
                elif backend == "paddleocr":
                    from paddleocr import PaddleOCR

                    model = PaddleOCR(
                        lang=config.get("lang", "es"),
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                elif backend == "reference_diff":
                    model = config
                else:
                    raise InferenceError(f"Backend no implementado en runtime: {backend}")
            except InferenceError:
                raise
            except Exception as exc:
                raise InferenceError(f"No se pudo cargar {model_id}: {exc}") from exc
            self._loaded[model_id] = model
            return model

    def _load_torchvision(self, config: dict[str, Any]) -> dict[str, Any]:
        import torch
        from torchvision import models

        architecture = config["architecture"]
        builders = {
            "efficientnet_b0": (models.efficientnet_b0, models.EfficientNet_B0_Weights.DEFAULT),
            "resnet50": (models.resnet50, models.ResNet50_Weights.DEFAULT),
            "vit_b_16": (models.vit_b_16, models.ViT_B_16_Weights.DEFAULT),
        }
        if architecture not in builders:
            raise InferenceError(f"Arquitectura torchvision no soportada: {architecture}")
        builder, weights = builders[architecture]
        model = builder(weights=weights)
        categories = list(weights.meta.get("categories", []))
        weights_path = config.get("weights_path")
        classes_path = config.get("classes_path")
        if weights_path:
            if not classes_path:
                raise InferenceError("Un clasificador personalizado requiere classes_path.")
            classes_file = Path(classes_path)
            if not classes_file.is_absolute():
                classes_file = Path(__file__).resolve().parents[2] / classes_file
            categories = json.loads(classes_file.read_text(encoding="utf-8"))
            num_classes = len(categories)
            if architecture == "efficientnet_b0":
                model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, num_classes)
            elif architecture == "resnet50":
                model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
            elif architecture == "vit_b_16":
                model.heads.head = torch.nn.Linear(model.heads.head.in_features, num_classes)
            path = Path(weights_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[2] / path
            state = torch.load(path, map_location="cpu")
            model.load_state_dict(state)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device).eval()
        return {
            "model": model,
            "device": device,
            "transform": weights.transforms(),
            "categories": categories,
        }

    def list_models(self) -> list[dict[str, Any]]:
        output = []
        loaded = set(self._loaded)
        for spec in self.registry.list():
            item = dict(spec)
            item["available"] = self.registry.backend_available(spec["backend"])
            item["loaded"] = spec["id"] in loaded
            output.append(item)
        return output

    def localize(
        self,
        image: np.ndarray,
        model_id: str | None,
        conf: float,
        iou: float,
        offset: tuple[int, int] = (0, 0),
    ) -> tuple[str, list[dict[str, Any]]]:
        spec = self._resolve("localization", model_id)
        model = self._load_model(spec)
        if spec["backend"] != "ultralytics":
            raise InferenceError("La localización requiere un backend compatible.")
        try:
            result = model.predict(source=image, conf=conf, iou=iou, verbose=False)[0]
        except Exception as exc:
            raise InferenceError(f"Falló la inferencia de localización: {exc}") from exc
        names = result.names
        detections = []
        if result.boxes is not None:
            for box in result.boxes:
                xyxy = box.xyxy[0].detach().cpu().tolist()
                class_id = int(box.cls[0].detach().cpu().item())
                confidence = float(box.conf[0].detach().cpu().item())
                detections.append(
                    {
                        "class_id": class_id,
                        "class_name": str(names[class_id]),
                        "confidence": confidence,
                        "bbox": map_bbox(xyxy, offset),
                    }
                )
        return spec["id"], detections

    def classify(
        self,
        image: np.ndarray,
        model_id: str | None,
        top_k: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        spec = self._resolve("classification", model_id)
        loaded = self._load_model(spec)
        if spec["backend"] != "torchvision":
            raise InferenceError("La clasificación requiere un backend compatible.")
        import torch
        from PIL import Image

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = loaded["transform"](Image.fromarray(rgb)).unsqueeze(0).to(loaded["device"])
        with torch.inference_mode():
            probabilities = loaded["model"](tensor).softmax(dim=1)[0]
        count = min(top_k, probabilities.shape[0])
        values, indices = torch.topk(probabilities, k=count)
        categories = loaded["categories"]
        predictions = []
        for value, index in zip(values.detach().cpu().tolist(), indices.detach().cpu().tolist()):
            name = categories[index] if index < len(categories) else str(index)
            predictions.append({"class_id": int(index), "class_name": str(name), "confidence": float(value)})
        return spec["id"], predictions

    def ocr(
        self,
        image: np.ndarray,
        model_id: str | None,
        offset: tuple[int, int] = (0, 0),
    ) -> tuple[str, list[dict[str, Any]]]:
        spec = self._resolve("ocr", model_id)
        model = self._load_model(spec)
        if spec["backend"] != "paddleocr":
            raise InferenceError("OCR requiere un backend compatible.")
        try:
            predictions = model.predict(image)
        except Exception as exc:
            raise InferenceError(f"Falló la inferencia OCR: {exc}") from exc
        items: list[dict[str, Any]] = []
        for prediction in predictions:
            payload = prediction.json
            data = payload.get("res", payload)
            texts = data.get("rec_texts", [])
            scores = data.get("rec_scores", [])
            polygons = data.get("rec_polys", [])
            for text, score, polygon in zip(texts, scores, polygons):
                points = np.asarray(polygon).astype(float).tolist()
                items.append(
                    {
                        "text": str(text),
                        "confidence": float(score),
                        "polygon": map_polygon(points, offset),
                    }
                )
        return spec["id"], items

    def anomaly_reference(
        self,
        image: np.ndarray,
        reference: np.ndarray,
        model_id: str | None,
        threshold: int | None,
        offset: tuple[int, int] = (0, 0),
    ) -> tuple[str, float, list[dict[str, Any]]]:
        spec = self._resolve("anomaly", model_id)
        config = self._load_model(spec)
        if spec["backend"] != "reference_diff":
            raise InferenceError("El modelo seleccionado requiere un runtime entrenado no configurado.")
        if image.shape[:2] != reference.shape[:2]:
            raise InferenceError("La imagen y la referencia deben tener el mismo tamaño.")
        value = int(threshold if threshold is not None else config.get("threshold", 25))
        min_area = int(config.get("min_area", 64))
        target_lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        reference_lab = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB)
        target_l = cv2.GaussianBlur(target_lab[:, :, 0], (5, 5), 0)
        reference_l = cv2.GaussianBlur(reference_lab[:, :, 0], (5, 5), 0)
        diff = cv2.absdiff(target_l, reference_l)
        _, mask = cv2.threshold(diff, value, 255, cv2.THRESH_BINARY)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        regions = []
        max_score = 0.0
        for label in range(1, count):
            x, y, w, h, area = stats[label].tolist()
            if area < min_area:
                continue
            component = diff[labels == label]
            score = float(component.mean() / 255.0) if component.size else 0.0
            max_score = max(max_score, score)
            regions.append(
                {
                    "score": score,
                    "area": int(area),
                    "bbox": map_bbox([x, y, x + w, y + h], offset),
                }
            )
        anomaly_score = max(max_score, float(diff.mean() / 255.0))
        return spec["id"], anomaly_score, regions


registry = ModelRegistry()
inference_service = InferenceService(registry)
