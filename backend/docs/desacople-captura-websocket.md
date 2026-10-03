# Desacople de captura y comunicación WebSocket

**Depende de:** M02 y M03 (acceso exclusivo a la cámara, [M03-acceso-exclusivo-camara.md](M03-acceso-exclusivo-camara.md)).

## Alcance

Separar el ciclo de adquisición del ciclo de comunicación WebSocket para que la velocidad o la desconexión del único cliente no controle, bloquee ni deje inconsistente la captura.

Sigue habiendo una sola cámara y un solo cliente (M03). No se distribuyen frames entre varios clientes.

## Cómo funciona

Antes, un mismo bucle dentro del router leía la cámara, serializaba y enviaba. Si el envío tardaba, la siguiente lectura esperaba. Ahora son tres responsabilidades en tareas distintas:

| Responsabilidad | Dónde vive | Qué hace |
|---|---|---|
| Captura | `_capture_loop` en `app/services/camera_session_manager.py` | Lee la cámara a `TARGET_FPS`, actualiza métricas y publica el frame completo en el slot. No conoce al cliente. |
| Serialización | `app/services/stream_protocol.py` | Convierte frame y metadatos al mensaje binario. Solo se serializa el frame que se va a enviar. |
| Comunicación | `app/services/stream_runner.py` | Emisor, receptor y (opcional) inferencia. Lo usan `/ws/stream` y `/ws/inference-stream`. |

El punto de unión es `FrameSlot` (`app/services/frame_slot.py`): un buffer de **un solo frame** con número de secuencia. La captura lo sobrescribe en cada lectura. El emisor pide "el frame más nuevo posterior al último que envié"; si tardó en enviar, al volver recibe el más reciente y los intermedios se descartan.

Como no hay cola, el retraso no puede acumularse: la antigüedad de un frame al enviarse está acotada por un intervalo de captura, sin importar qué tan lento sea el cliente.

### Tareas por conexión

- **Captura.** Arranca en `acquire()` y se detiene en `release()`. Pertenece a la sesión.
- **Emisor.** Espera el siguiente frame del slot, lo serializa y lo envía.
- **Receptor.** Escucha el socket. Es lo que permite detectar la desconexión aunque el emisor esté detenido en un envío lento.
- **Inferencia** (solo `/ws/inference-stream`). Consume el mismo slot y deja las últimas detecciones disponibles para el emisor. Una inferencia lenta ya no baja los FPS del video; las cajas se actualizan con menos frecuencia.

### Desconexión ordenada

Cuando termina cualquiera de las tareas del cliente (se desconecta, la cámara deja de dar frames o hay un error):

1. Se cancelan las demás tareas del cliente y se espera a que terminen.
2. `release()` cancela la tarea de captura y espera a que concluya la lectura en curso.
3. Solo entonces se cierra la cámara y la sesión queda `idle`.

Si `read_frame()` sigue bloqueado pasado el margen de espera (`FRAME_STALE_TIMEOUT_S`), la sesión queda `idle` pero el `release()` del driver **no** se ejecuta todavía: queda programado para el momento en que esa lectura termine. La cámara nunca se cierra con una lectura en curso.

## Decisión: desacople por frame completo, no por ROI

La captura publica siempre el frame entero. El ROI se aplica después, únicamente en la tarea de inferencia.

- El frontend dibuja el frame completo en un canvas y superpone los ROI encima; recibir un recorte rompería el visor.
- El ROI es un parámetro del cliente (hay varios por cámara, editables). Si la captura dependiera de él, la adquisición volvería a quedar acoplada al cliente.
- El backend ya devolvía las detecciones en coordenadas del frame completo; eso no cambia.

## Contrato para los clientes

El formato binario no cambia: `[4 bytes uint32 BE = longitud JSON] [JSON] [JPEG]`.

Cambios en el JSON de cada frame (aditivos):

| Campo | Antes | Ahora |
|---|---|---|
| `seq` | no existía | Número de secuencia de captura. Los saltos indican frames descartados. |
| `timestamp` | Hora de serialización | Hora de captura del frame. `ahora − timestamp` es la latencia real. |

`/ws/inference-stream` usa ahora los mismos mensajes de conexión que `/ws/stream` (campo `error` definido en M03). Se agregan dos códigos de cierre durante la transmisión:

| `error` | Código de cierre | Significado |
|---|---|---|
| `STREAM_ERROR` | 1011 | Falló la inferencia (modelo, ROI fuera de la imagen) o el envío. |
| `CAMERA_READ_ERROR` | 1011 | El driver lanzó una excepción al leer. |

`GET /cameras/session` agrega el bloque `delivery`:

```json
"delivery": {"frames_sent": 11, "frames_skipped": 56}
```

`metrics.frames_total` cuenta frames capturados; `delivery` cuenta lo que llegó al cliente.

## Pruebas

Corren sin cámara física: la cámara y el WebSocket son dobles de prueba.

```powershell
cd backend
python -m pytest -v
```

| Criterio | Pruebas |
|---|---|
| El envío lento no bloquea la adquisición | `test_cliente_lento_no_bloquea_la_captura` |
| Captura, serialización y comunicación separadas | `test_frame_slot.py`, `test_inferencia_lenta_no_frena_el_video` |
| Cliente lento conserva frames recientes sin retraso acumulado | `test_cliente_lento_recibe_frames_recientes_sin_retraso_acumulado` |
| La desconexión cancela ordenadamente las tareas | `test_desconexion_cancela_tareas_y_libera_la_camara`, `test_desconexion_detiene_la_captura_antes_de_liberar` |
| La cámara no se cierra mientras `read_frame()` sigue bloqueado | `test_release_no_cierra_la_camara_mientras_read_frame_sigue_bloqueado`, `test_shutdown_no_cierra_la_camara_mientras_read_frame_sigue_bloqueado`, `test_desconexion_con_read_frame_bloqueado_libera_la_sesion_sin_cerrar_a_mitad` |

Las pruebas de M03 (`test_camera_exclusive_access.py`) siguen pasando sin modificarse.

## Demostración sin cámara física

### Automática

```powershell
cd backend
python scripts/demo_desacople_stream.py
```

Ejecuta el código real de `/ws/stream` contra una cámara simulada y tres clientes simulados con envíos de 0 ms, 250 ms y 1000 ms. Resultado de referencia:

| Cliente | Capturados | Enviados | Saltados | Antigüedad máx. al enviar |
|---|---|---|---|---|
| Rápido (0 ms) | 79 | 79 | 0 | 6 ms |
| Lento (250 ms) | 73 | 11 | 56 | 48 ms |
| Muy lento (1000 ms) | 80 | 3 | 76 | 44 ms |

La captura mantiene su ritmo en los tres casos y la antigüedad no crece con la lentitud del cliente. Tras desconectar: sesión `idle`, cámara liberada una vez y cero tareas pendientes.

### Manual con el servidor

1. Inicia el servidor con un solo worker: `uvicorn app.main:app`.
2. Conecta un cliente WebSocket a `ws://127.0.0.1:8000/ws/stream?camera_id=RUTA_A_UN_VIDEO.mp4`.
3. Consulta `GET /cameras/session` varias veces: `metrics.frames_total` y `delivery.frames_sent` avanzan a la par.
4. Haz que el cliente deje de leer del socket unos segundos y vuelve a consultar: `frames_total` sigue avanzando mientras `frames_sent` se detiene. Cuando el cliente reanuda, `frames_skipped` sube de golpe y recibe un frame actual.
5. Cierra el cliente y consulta de nuevo: `status` es `idle`.

Verificado así con uvicorn y un cliente de la librería `websockets` (`max_queue=1`) sobre un video de 640×480 con ruido (~160 KB por mensaje): en 3 s sin leer, la captura pasó de 20 a 97 frames mientras el envío se quedó en 26.

Para que el paso 4 se note, el video debe tener contenido pesado y el cliente debe dejar de leer de verdad. Con frames pequeños, los buffers de red y del propio cliente absorben varios segundos de video y el servidor no llega a percibir la lentitud.

## Limitaciones conocidas

- **Liberación con una lectura colgada.** Al liberar se espera hasta `FRAME_STALE_TIMEOUT_S` (5 s) a que termine la lectura en curso. Con una fuente RTSP que no responde, el siguiente cliente puede esperar ese tiempo. Si la lectura sigue colgada después, el cierre del driver queda diferido: la sesión ya está libre, pero el siguiente `acquire()` de esa misma cámara puede fallar con `CAMERA_UNAVAILABLE` hasta que la lectura termine y el dispositivo se cierre.
- **Ritmo de captura en Windows.** El temporizador del sistema (~15 ms) hace que la captura simulada ronde 22–32 FPS con un objetivo de 30.
- **Cambio de parámetros en vivo.** Cambiar `conf`, `iou` o el ROI sigue requiriendo reconectar. La tarea receptora deja el lugar para hacerlo por mensaje, pero no está implementado.
- **`ws_max_queue_size`.** Queda sin uso: el slot es de tamaño 1 por diseño.
