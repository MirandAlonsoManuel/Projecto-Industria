# Kaggle GPU

## 1. Localización

Usa `01_yolo_localization_benchmark.ipynb`.

Adjunta un dataset de detección en formato YOLO con `data.yaml`, activa GPU y cambia `DATA_YAML`.

El notebook compara YOLO26n, YOLO26s y YOLO11n con el mismo split.

## 2. Clasificación

Usa `02_classification_benchmark.ipynb`.

Adjunta un dataset compatible con `ImageFolder`:

```text
train/clase_a
train/clase_b
val/clase_a
val/clase_b
```

Compara EfficientNet-B0, ResNet50 y ViT-B/16.

## 3. Anomalías

Usa `03_anomaly_benchmark.ipynb`.

Adjunta MVTec AD o un dataset industrial con imágenes normales y anómalas. El notebook deja preparado el entorno de Anomalib para PatchCore y EfficientAD.
