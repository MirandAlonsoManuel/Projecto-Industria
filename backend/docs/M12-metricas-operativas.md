# M12 — Métricas operativas de cámara y streaming

**Ticket:** OMC-93 · **Secuencia:** M12 · **Se construye sobre:** M07 (ciclo de vida), M10 (vigilancia y recuperación) y el desacople de captura y WebSocket

## Alcance

Registrar frames capturados y descartados, estado del único cliente, reconexiones, última actividad y último error de la única cámara configurada.

## Resumen

Antes de M12, las métricas existían pero estaban repartidas: unas en el estado de la sesión, otras en el bloque de entrega del desacople, otras en el bloque de recuperación de M10, y todas desaparecían al cerrarse la sesión. Además, el identificador de la cámara se mostraba tal cual en todas las salidas, y una URL RTSP con usuario y contraseña quedaba visible para cualquiera que consultara el estado.

M12 reúne todo en un solo endpoint, `GET /cameras/metrics`, conserva acumulados desde que arranca el servicio y enmascara las credenciales en todas las salidas.

## La consulta

```
GET /cameras/metrics
```

Responde con la estructura uniforme de la API (`data`, `error`, `meta`). Dentro de `data`:

| Bloque | Campo | Significado |
|---|---|---|
| `camera` | `camera_id` | Fuente de la sesión, sin credenciales; `null` sin sesión |
| | `state` | `idle`, `running`, `streaming`, `recovering` o `stopping` |
| | `health` | `ok` o `error` según la salud de la sesión; `null` sin sesión |
| | `started_by` | `client` u `operator` |
| | `fps_current`, `uptime_seconds` | Ritmo de captura y tiempo de la sesión |
| | `last_activity_ts`, `seconds_without_frames`, `stale_timeout_s` | Última actividad y vigilancia (M10) |
| `client` | `connected` | **0 o 1**: si hay un cliente conectado |
| | `client_id`, `connected_since` | Identificador aleatorio del cliente y desde cuándo está conectado |
| | `connections_total` | Conexiones aceptadas desde que arrancó el servicio |
| | `rejections_total` | Conexiones rechazadas (`CAMERA_BUSY`, `CAMERA_MISMATCH`, `SERVICE_SHUTTING_DOWN`) |
| `frames` | `captured` | Frames válidos leídos de la cámara |
| | `dropped` | Lecturas sin imagen: frames vacíos o errores del driver |
| | `sent` | Frames enviados al cliente |
| | `skipped` | Frames que el cliente se saltó por ir más lento que la captura |
| `recoveries` | `recovered`, `failed` | Recuperaciones de cámara exitosas y fallidas (M10) |
| `errors` | — | Cantidad de errores registrados |
| `last_error` | `timestamp`, `message` | Último error, sin credenciales; `null` si no hubo |
| `service` | `started_at`, `uptime_seconds` | Arranque del servicio |
| | `sessions_started` | Sesiones abiertas desde el arranque |
| | `accepting_clients` | `false` después del apagado global |

Los bloques `frames`, `recoveries` y `errors` se reportan dos veces: `session` (la sesión actual, en cero si no hay) y `since_start` (las sesiones cerradas más la actual).

## Decisiones técnicas

**Dos tipos de descarte.** "Frames descartados" puede significar dos cosas distintas, y por eso se reportan por separado. `dropped` son lecturas en las que la cámara no entregó imagen: indican un problema de la cámara. `skipped` son frames que sí se capturaron, pero que el cliente no alcanzó a recibir porque iba más lento: indican un cliente o una red lentos. Sumarlos en un solo número escondería cuál de los dos problemas ocurre.

**Reconexiones.** En este sistema, "reconexión" se refiere a la cámara: es el mecanismo de recuperación de M10, que cierra y vuelve a abrir el dispositivo. Por eso se reporta en `recoveries`. Las entradas y salidas de clientes son visibles en `connections_total` y `rejections_total`.

**Acumulados sin doble conteo.** Al cerrarse una sesión, sus contadores se suman a los del servicio (`ServiceCounters.absorb`). `since_start` es la suma de esos acumulados y la sesión actual. Mientras una sesión se está cerrando (estado `stopping`), sus contadores siguen contando como sesión actual hasta que se absorben, así que nunca desaparecen ni se cuentan dos veces.

**Un cliente: 0 o 1.** `connected` no es un contador que se suma y se resta, sino que se deriva del único cliente activo de la sesión. Es imposible que valga 2, porque el gestor solo admite un cliente (M03), y una prueba lo verifica muestreando las métricas mientras varios clientes compiten por conectarse.

**Métricas que corresponden al estado real.** Todo se calcula en el momento de la consulta, a partir del estado del gestor, sin copias que puedan quedar desactualizadas.

## Credenciales y datos sensibles

Las cámaras IP suelen llevar credenciales en la URL, por ejemplo `rtsp://admin:clave@10.0.0.5/stream` o `rtsp://10.0.0.5/stream?token=abc`. El gestor necesita esa URL para abrir la cámara, pero nada de lo que sale de él debe contenerla.

`app/services/redaction.py` ofrece dos funciones:

- `redact_source(fuente)` enmascara el usuario y la contraseña (`rtsp://***@10.0.0.5/stream`) y los valores de parámetros sensibles (`password`, `token`, `key`, `secret`, `auth`, `user`, entre otros). Los índices USB y las rutas de archivo no cambian.
- `redact_text(texto, fuentes...)` limpia textos libres, como mensajes de error del driver, que suelen incluir la URL.

Se aplican en todas las salidas: métricas, `GET /cameras/session`, eventos del ciclo de vida, historial de errores, logs del servidor, mensajes del WebSocket (bienvenida, rechazos, metadatos de cada frame) y respuestas de `start`. La dirección y el puerto de la cámara se conservan, porque son útiles para diagnosticar.

`client_id` es un identificador aleatorio que el servidor genera por conexión; no identifica a una persona ni a un equipo.

## Pruebas

Sin cámara física. Cada apertura entrega una cámara con un guion exacto de lecturas (por ejemplo, 10 frames buenos, 3 vacíos y 2 errores) que al terminar se queda esperando, de modo que los contadores quedan fijos y se comparan contra lo que realmente ocurrió.

```powershell
cd backend
python -m pytest tests/test_metrics.py -v
```

| Criterio | Pruebas |
|---|---|
| Las métricas son consultables y corresponden al estado real | `test_c1_frames_capturados_perdidos_y_errores_exactos`, `test_c1_estado_de_la_camara_coincide_con_el_ciclo_de_vida`, `test_c1_los_acumulados_sobreviven_al_cierre_de_la_sesion`, `test_c1_recuperaciones_reflejan_lo_ocurrido`, `test_c1_enviados_coinciden_con_lo_que_recibe_el_cliente`, `test_endpoint_de_metricas_tiene_estructura_estable` |
| La cantidad de clientes solo puede ser 0 o 1 | `test_c2_sin_cliente_cero_con_cliente_uno`, `test_c2_bajo_concurrencia_nunca_hay_mas_de_un_cliente` |
| Los contadores no exponen credenciales ni datos sensibles | `test_c3_enmascaramiento_de_fuentes`, `test_c3_enmascaramiento_en_texto_libre`, `test_c3_el_driver_recibe_la_url_real_pero_ninguna_salida_la_contiene`, `test_c3_errores_al_abrir_no_filtran_credenciales`, `test_c3_websocket_y_rest_no_devuelven_credenciales` |

Las pruebas de credenciales usan una URL con contraseña y token, y revisan que ninguno de los dos aparezca en ninguna salida, incluidos los logs. Se verificó que, si se quita el enmascaramiento del gestor o del WebSocket, fallan.

## Demostración funcional

Con el servidor en marcha (`uvicorn app.main:app --port 8000 --workers 1`), en Postman:

1. `GET /cameras/metrics` sin sesión: `client.connected` es 0, `camera.state` es `idle` y los contadores de sesión están en cero.
2. Conecta `ws://localhost:8000/ws/stream?camera_id=0` y repite la consulta: `connected` es 1, `captured` y `sent` avanzan.
3. Abre un segundo WebSocket: se rechaza con `CAMERA_BUSY`, `rejections_total` sube a 1 y `connected` sigue en 1.
4. Desconecta y consulta: los contadores de `session` vuelven a cero, pero `since_start` conserva lo capturado.
5. Credenciales: con el servidor en marcha, conecta `ws://localhost:8000/ws/stream?camera_id=rtsp://admin:clave@10.0.0.5/stream`. La cámara no existe, así que la conexión se rechaza con `CAMERA_UNAVAILABLE` (puede tardar varios segundos mientras OpenCV intenta conectar); revisa que el mensaje, las métricas, el estado y la consola del servidor muestren `rtsp://***@10.0.0.5/stream`.

## Limitaciones conocidas

- **Mensajes internos de OpenCV.** OpenCV puede escribir advertencias propias en la consola, fuera del sistema de logs de Python, y algunas incluyen la URL. El enmascaramiento cubre todo lo que produce la aplicación, pero no esas advertencias de la librería.
- **Rutas de archivo.** Se muestran completas. Si una ruta contiene información sensible, debe evitarse como fuente.
- **Acumulados en memoria.** Los contadores `since_start` se reinician al reiniciar el servidor; no se persisten.
- **`dropped` incluye la última lectura al cerrar.** Si la cámara estaba esperando un frame cuando se cerró la sesión, esa lectura termina sin imagen y se cuenta como perdida.

## Archivos

| Archivo | Cambio |
|---|---|
| `app/services/redaction.py` | Nuevo: enmascaramiento de fuentes y textos |
| `app/services/camera_session_manager.py` | `get_metrics()`, contadores acumulados, `connected_since`, conteo de errores y rechazos, y enmascaramiento en estado, eventos, errores y logs |
| `app/services/stream_runner.py` | Mensajes del WebSocket con la fuente enmascarada |
| `app/api/routers/cameras.py` | Endpoint `GET /cameras/metrics` y mensaje de `start` enmascarado |
| `tests/test_metrics.py` | Nuevas pruebas de M12 |
