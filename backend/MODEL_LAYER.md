# Capa de modelos

La API original de cámaras y streaming se conserva sin cambios.

## Endpoints añadidos

- `GET /models`
- `POST /inference/localization`
- `POST /inference/classification`
- `POST /inference/ocr`
- `POST /inference/anomaly`
- `WS /ws/inference-stream`

## Tareas

### Localización

Modelos registrados:

- `yolo26n-localization`
- `yolo26s-localization`
- `yolo11n-localization`

Ejemplo:

```bash
curl -X POST "http://127.0.0.1:8000/inference/localization?model_id=yolo26n-localization&conf=0.25" -F "image=@pieza.jpg"
```

Con ROI:

```bash
curl -X POST "http://127.0.0.1:8000/inference/localization?roi=100,50,640,480" -F "image=@pieza.jpg"
```

### Clasificación

Modelos registrados:

- `efficientnet-b0-classification`
- `resnet50-classification`
- `vit-b16-classification`

Ejemplo:

```bash
curl -X POST "http://127.0.0.1:8000/inference/classification?top_k=5" -F "image=@pieza.jpg"
```

Los pesos ImageNet son una línea base. Las clases industriales requieren fine-tuning y pesos propios.

### OCR

Modelo registrado:

- `paddleocr-es`

Ejemplo:

```bash
curl -X POST "http://127.0.0.1:8000/inference/ocr?roi=50,50,800,300" -F "image=@etiqueta.jpg"
```

### Anomalías

Baseline registrado:

- `reference-diff-v1`

Ejemplo:

```bash
curl -X POST "http://127.0.0.1:8000/inference/anomaly?difference_threshold=25" -F "image=@pieza.jpg" -F "reference_image=@referencia.jpg"
```

`patchcore-candidate` y `efficientad-candidate` quedan registrados como candidatos de entrenamiento y deshabilitados en runtime hasta contar con artefactos entrenados.

## Streaming con localización

El WebSocket original `/ws/stream` no se modifica.

El nuevo stream opcional es:

```text
ws://127.0.0.1:8000/ws/inference-stream?camera_id=0&model_id=yolo26n-localization&infer_every_n_frames=3
```

## Instalación

Base:

```bash
pip install -r requirements.txt
```

Modelos:

```bash
pip install -r requirements-models.txt
```

Entrenamiento avanzado de anomalías:

```bash
pip install -r requirements-anomaly-training.txt
```

## Registro

Los modelos se configuran en:

```text
config/model_registry.json
```

## Registrar pesos entrenados en Kaggle

YOLO personalizado:

```json
{
  "id": "yolo26-product-v1",
  "task": "localization",
  "backend": "ultralytics",
  "default": false,
  "enabled": true,
  "config": {
    "weights": "models/localization/best.pt"
  }
}
```

Clasificador personalizado:

```json
{
  "id": "efficientnet-product-v1",
  "task": "classification",
  "backend": "torchvision",
  "default": false,
  "enabled": true,
  "config": {
    "architecture": "efficientnet_b0",
    "weights_path": "models/classification/efficientnet_b0_best.pth",
    "classes_path": "models/classification/classes.json"
  }
}
```
