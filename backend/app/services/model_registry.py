from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from threading import RLock
from typing import Any


class ModelRegistryError(ValueError):
    pass


class ModelRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "model_registry.json"
        self._lock = RLock()
        self._models = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            raise ModelRegistryError(f"No existe el registro de modelos: {self._path}")
        data = json.loads(self._path.read_text(encoding="utf-8"))
        models = data.get("models", [])
        result: dict[str, dict[str, Any]] = {}
        for item in models:
            model_id = item.get("id")
            if not model_id or model_id in result:
                raise ModelRegistryError("El registro contiene IDs inválidos o duplicados.")
            result[model_id] = item
        return result

    def get(self, model_id: str) -> dict[str, Any]:
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                raise ModelRegistryError(f"Modelo no registrado: {model_id}")
            if not model.get("enabled", True):
                raise ModelRegistryError(f"Modelo deshabilitado: {model_id}")
            return model

    def default_for(self, task: str) -> dict[str, Any]:
        with self._lock:
            candidates = [m for m in self._models.values() if m.get("task") == task and m.get("enabled", True)]
            for model in candidates:
                if model.get("default", False):
                    return model
            if candidates:
                return candidates[0]
        raise ModelRegistryError(f"No hay modelos habilitados para la tarea: {task}")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(model) for model in self._models.values()]

    @staticmethod
    def backend_available(backend: str) -> bool:
        modules = {
            "ultralytics": "ultralytics",
            "torchvision": "torchvision",
            "paddleocr": "paddleocr",
            "reference_diff": "cv2",
            "anomalib": "anomalib",
        }
        module = modules.get(backend)
        return bool(module and importlib.util.find_spec(module))
