# Contrato de `/ws/inference-stream`

Endpoint WebSocket de inferencia en vivo. Una cámara, un cliente. Lo consume el
frontend; este documento es el contrato del backend.

## Conexión

`ws://<host>/ws/inference-stream?camera_id=0&model_id=...&conf=0.25&iou=0.45&infer_every_n_frames=3`

ROI opcional en la URL: `roi=x,y,ancho,alto` o `x1,y1,x2,y2`.

Si el servidor rechaza la conexión (`CAMERA_BUSY`, `CAMERA_UNAVAILABLE`, ...)
envía un JSON `{"connected": false, "error": "...", "description": "..."}` y cierra.

## Mensajes servidor → cliente

1. **Texto** `{"connected": true, "camera_id": ..., "client_id": ..., ...}` al conectar.
2. **Binario** por frame: `[4 B uint32 BE = longitud JSON][JSON][JPEG]`.

### Metadatos de cada frame binario

| Campo | Significado |
|---|---|
| `frame_width`, `frame_height` | Tamaño del frame **original**, en píxeles. Las cajas están en este sistema. |
| `detections` | Lista de detecciones. |

### Detección

```json
{"class_id": 3, "class_name": "tornillo", "confidence": 0.91,
 "bbox": {"x1": 120.0, "y1": 80.0, "x2": 220.0, "y2": 190.0}}
```

`bbox` está en píxeles del **frame original**, aunque la inferencia haya corrido
sobre una ROI (se le suma el desplazamiento de la ROI), recortado a
`[0, frame_width] × [0, frame_height]`. Una caja que queda sin área dentro del
frame (totalmente fuera, o degenerada) se descarta. Una caja parcialmente fuera
se recorta. El resultado no depende del tamaño en que el cliente muestre el
video: el escalado a canvas es responsabilidad del frontend.
