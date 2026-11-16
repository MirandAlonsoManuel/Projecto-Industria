# Contrato de `/ws/inference-stream`

Endpoint WebSocket de inferencia en vivo. Una cámara, un cliente. Lo consume el
frontend; este documento es el contrato del backend.

## Conexión

`ws://<host>/ws/inference-stream?camera_id=0&model_id=...&conf=0.25&iou=0.45&infer_every_n_frames=3`

ROI **inicial** opcional en la URL: `roi=x,y,ancho,alto` o `x1,y1,x2,y2`. Para
cambiarla durante la sesión se usa `update_roi` (abajo); no hace falta
reconectar ni reabrir la cámara.

Si el servidor rechaza la conexión (`CAMERA_BUSY`, `CAMERA_UNAVAILABLE`, ...)
envía un JSON `{"connected": false, "error": "...", "description": "..."}` y cierra.

## Mensajes servidor → cliente

1. **Texto** `{"connected": true, "camera_id": ..., "client_id": ..., ...}` al conectar.
2. **Binario** por frame: `[4 B uint32 BE = longitud JSON][JSON][JPEG]`.
3. **Texto** de control: `roi_updated` y `error` (ver abajo).

### Metadatos de cada frame binario

| Campo | Significado |
|---|---|
| `seq` | Número de frame. La imagen y `detections` pertenecen a este `seq`. |
| `captured_at` | Instante de captura (igual a `timestamp`, que se conserva por compatibilidad). |
| `frame_width`, `frame_height` | Tamaño del frame **original**, en píxeles. Las cajas están en este sistema. |
| `detections` | Cajas calculadas sobre **este mismo frame**. Nunca se reutilizan las de otro. |
| `detections_status` | `ok`, `skipped`, `timeout`, `busy`, `roi_out_of_frame`, `disabled`. |
| `roi` | ROI con la que se infirió este frame (`{x1,y1,x2,y2}` o `null`). |
| `roi_version` | Versión de configuración de ROI usada. Sube con cada `update_roi` válido. |

`detections` solo es significativo cuando `detections_status == "ok"`; en
cualquier otro estado es `[]`. Una lista vacía con `ok` significa "se infirió y no
hay objetos". Estados:

- `ok`: las detecciones se calcularon sobre este frame.
- `skipped`: este frame no tocaba inferir (`infer_every_n_frames`).
- `timeout`: la inferencia de este frame no terminó a tiempo (0.1 s por defecto); el video sigue.
- `busy`: sigue en curso una inferencia anterior (máximo una en vuelo, sin cola).
- `roi_out_of_frame`: la ROI activa no cabe en este frame.
- `disabled`: el stream no tiene inferencia.

Si la inferencia es lenta, el backend prioriza lo actual: el video continúa con
el frame más reciente y no se acumula ninguna cola de frames ni de inferencias.

**Plazo de inferencia.** Como imagen y detecciones viajan juntas, un frame solo lleva
detecciones si su inferencia termina dentro de `inference_timeout_s` (0.1 s por
defecto; parámetro opcional de la URL, mayor que 0 y hasta 5 s). Con un modelo más
lento que el plazo, los frames salen con `timeout` o `busy` y sin detecciones: el video
no se frena, pero no hay cajas. En equipos sin GPU puede hacer falta subirlo (por
ejemplo `inference_timeout_s=0.5`), a costa de menos frames por segundo mientras dure
cada inferencia.

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

## Mensajes cliente → servidor

```json
{"type": "update_roi", "request_id": "opcional", "roi": {"x1": 10, "y1": 20, "x2": 300, "y2": 240}}
{"type": "update_roi", "request_id": "opcional", "roi": null}
```

Coordenadas **absolutas** del frame original, enteros (las esquinas pueden venir
en cualquier orden). `null` vuelve al frame completo. El cambio se aplica de
forma atómica a los frames posteriores: cada frame se infiere con una ROI completa
y su mensaje informa `roi` y `roi_version`.

Confirmación:

```json
{"type": "roi_updated", "ok": true, "request_id": "...", "roi": {...}|null,
 "roi_version": 3, "frame_width": 640, "frame_height": 480}
```

## Errores recuperables

```json
{"type": "error", "error": "INVALID_ROI", "recoverable": true, "request_id": "...",
 "description": "...", "roi": {...}|null, "roi_version": 2}
```

| `error` | Causa |
|---|---|
| `INVALID_ROI` | Formato o valores inválidos (negativos, área cero, no enteros, claves incorrectas). |
| `ROI_OUT_OF_FRAME` | La ROI no cabe en el frame actual. |
| `INVALID_MESSAGE` | No es JSON, no es un objeto, falta `roi` o es demasiado grande. |
| `UNKNOWN_MESSAGE_TYPE` | `type` distinto de `update_roi`. |

Todo error es **recuperable**: el socket sigue abierto y se conserva la última
ROI válida (la que viene en el propio error). Una ROI inválida en la URL inicial
produce el mismo error justo después de `connected`, y el stream arranca con el
frame completo. Si una ROI válida deja de caber en un frame (por ejemplo, cambió
la resolución), ese mensaje lleva `detections_status: "roi_out_of_frame"` y el
stream continúa.

## Ciclo de vida

- **Un cliente por cámara, sobre la sesión central.** La conexión usa el gestor de
  sesiones; no abre ningún dispositivo por su cuenta. Un segundo cliente recibe
  `{"connected": false, "error": "CAMERA_BUSY", ...}` y se cierra con 1008, sin
  afectar al primero.
- **Al desconectarse** el cliente se cancelan envío e inferencia, se libera el
  cliente y se cierra la cámara una sola vez (si la conexión la abrió; si un
  operador la inició antes, sigue abierta).
- **Estado limpio.** La ROI, `roi_version` y las detecciones viven solo en la
  conexión, y el último frame pertenece a la sesión de cámara: una conexión nueva
  empieza con `roi: null`, `roi_version: 0` y un frame de la cámara recién abierta.
- **Reapertura fallida.** Si la cámara no puede reabrirse, el cliente recibe
  `CAMERA_UNAVAILABLE` (cierre 1000) y la sesión no queda ocupada: la siguiente
  conexión puede intentarlo de nuevo.
- **Concurrencia.** Apertura, cierre y reconexión se serializan en el gestor: con
  varias conexiones simultáneas solo una gana y el resto recibe `CAMERA_BUSY`.

Códigos de cierre: 1000 normal, 1001 apagado del servicio, 1008 rechazo por
política (`CAMERA_BUSY`, `CAMERA_MISMATCH`), 1011 error interno (incluye un fallo
real del modelo, que cierra con `STREAM_ERROR`).
