# ROI en Backend e Inferencia

La implementación permite restringir la inferencia a una región rectangular de la imagen.

## Formato recomendado para Frontend

La ROI puede enviarse mediante dos puntos:

```text
x1,y1 = primera esquina
x2,y2 = esquina opuesta
```

El backend acepta los parámetros:

```text
x1

y1

x2

y2
```

El orden de arrastre no importa. El backend normaliza automáticamente las coordenadas.

## Formato alternativo

También se mantiene compatibilidad con:

```text
roi=x,y,width,height
```

No deben enviarse ambos formatos en la misma petición.

## Localización

```bash
curl -X POST \
  "http://127.0.0.1:8000/inference/localization?model_id=yolo26n-localization&conf=0.25&x1=100&y1=100&x2=400&y2=400" \
  -F "image=@/ruta/real/imagen.jpg"
```

## Clasificación

```bash
curl -X POST \
  "http://127.0.0.1:8000/inference/classification?model_id=efficientnet-b0-classification&top_k=5&x1=100&y1=100&x2=400&y2=400" \
  -F "image=@/ruta/real/imagen.jpg"
```

## OCR

```bash
curl -X POST \
  "http://127.0.0.1:8000/inference/ocr?model_id=paddleocr-es&x1=100&y1=100&x2=400&y2=250" \
  -F "image=@/ruta/real/imagen.jpg"
```

## Anomalías

```bash
curl -X POST \
  "http://127.0.0.1:8000/inference/anomaly?difference_threshold=25&x1=100&y1=100&x2=400&y2=400" \
  -F "image=@/ruta/real/evaluada.jpg" \
  -F "reference_image=@/ruta/real/referencia.jpg"
```

## WebSocket

```text
ws://127.0.0.1:8000/ws/inference-stream?camera_id=0&model_id=yolo26n-localization&x1=100&y1=100&x2=400&y2=400
```

## Respuesta

Las respuestas incluyen:

```text
roi
roi_points
```

`roi` usa:

```text
[x,y,width,height]
```

`roi_points` usa:

```text
[x1,y1,x2,y2]
```

Las detecciones y polígonos se remapean a las coordenadas de la imagen original.
