# M10 — Detección de una cámara abierta que deja de producir frames

**Ticket:** OMC-91 · **Secuencia:** M10 · **Se construye sobre:** el ciclo de vida de M07 y el desacople de captura y WebSocket

## Alcance

Implementar vigilancia de actividad para detectar cuando la única cámara permanece abierta pero deja de producir frames, y activar el mecanismo de recuperación.

## Resumen

Antes de M10 había dos fallas sin una respuesta adecuada. Si la cámara entregaba un solo frame vacío, la captura terminaba de inmediato y el cliente perdía la conexión, aunque fuera un tropiezo aislado. Y si la lectura se congelaba dentro del driver, nadie lo notaba: el video simplemente se detenía.

Ahora un frame vacío aislado solo cuenta como frame perdido. Un vigilante por sesión mide cuánto tiempo lleva la cámara sin frames válidos y, si se supera el umbral, dispara una recuperación controlada: cierra la cámara y la vuelve a abrir, sin desconectar al cliente. Si la cámara no vuelve, la sesión se cierra con un motivo claro.

No existía un mecanismo de recuperación previo (M09), así que M10 incluye uno mínimo y acotado, descrito más abajo. Si en el futuro se implementa M09, la recuperación vive en un solo método (`_recover`) y puede reemplazarse sin tocar la detección.

## Activa o estancada

La sesión registra su **última actividad**: el momento en que se abrió la cámara o en que llegó el último frame válido.

| Situación | Clasificación |
|---|---|
| Llegó un frame válido hace menos de `FRAME_STALE_TIMEOUT_S` (5 s) | **Activa** |
| Pasaron más de 5 s sin frames válidos | **Estancada** |

Una cámara estancada se clasifica por motivo:

| Motivo | Qué pasa | Cómo se distingue |
|---|---|---|
| `no_frames` | La cámara responde, pero entrega frames vacíos o el driver lanza errores al leer | Las lecturas terminan, pero sin imagen |
| `read_timeout` | La lectura se quedó congelada dentro del driver | Hay una lectura en curso que lleva más de la mitad del umbral (2.5 s) |

La captura lee la cámara continuamente, así que casi siempre hay una lectura en curso. Por eso el motivo no depende de *si* hay una lectura en curso, sino de *cuánto lleva*: una lectura normal dura un intervalo de captura (unos 33 ms a 30 FPS).

## El vigilante

Cada sesión tiene un vigilante (`_watchdog_loop`) que revisa la actividad cada `WATCHDOG_INTERVAL_S` (0.5 s). Arranca al abrir la sesión y se detiene al cerrarla.

Como la captura corre aunque no haya cliente conectado, la vigilancia también funciona en estado `running`, con una sesión iniciada por un operador.

## Recuperación controlada

Toda la recuperación ocurre dentro del candado del gestor:

1. La sesión pasa al estado `recovering` y se registra el evento `stalled`.
2. Se detiene la tarea de captura **sin cerrar el slot del cliente**: el cliente sigue conectado, esperando frames.
3. Si la lectura en curso sigue congelada, la cámara **no se cierra a la fuerza** (regla del desacople). La recuperación se declara fallida y el cierre del driver se difiere hasta que esa lectura termine.
4. Si no, se cierra la cámara y, solo entonces, se abre una nueva, con hasta `RECOVERY_MAX_ATTEMPTS` (3) intentos y esperas que se duplican: 0.5 s, 1 s y 2 s.
5. **Si se recupera**, se reinicia la captura y el mismo cliente vuelve a recibir frames en el mismo slot. Solo nota una pausa en el video.
6. **Si falla**, la sesión se cierra y el cliente recibe `CAMERA_STALLED`, con cierre WebSocket 1011.

Para evitar un ciclo infinito con una cámara que se reabre bien pero nunca entrega imagen, el gestor cuenta las recuperaciones seguidas sin ningún frame válido. Si la cámara vuelve a estancarse después de 3 recuperaciones sin imagen, se rinde. El contador vuelve a cero en cuanto llega un frame válido.

## Registro

`GET /cameras/session` agrega:

| Campo | Significado |
|---|---|
| `last_activity_ts` | Momento de la última actividad (apertura o último frame válido) |
| `seconds_without_frames` | Tiempo transcurrido desde esa actividad |
| `stale_timeout_s` | Umbral configurado |
| `recovery.total` | Recuperaciones de la sesión |
| `recovery.consecutive` | Recuperaciones seguidas sin frames válidos |
| `recovery.last_reason` | `no_frames` o `read_timeout` |
| `recovery.last_started_ts` | Inicio de la última recuperación |
| `recovery.last_attempts` | Intentos de apertura de la última recuperación |
| `recovery.last_result` | `recovered` o `failed` |

Mientras se recupera, `state` es `recovering`. El historial de eventos agrega:

| Evento | `reason` |
|---|---|
| `stalled` | `no_frames` o `read_timeout` |
| `recovered` | Motivo e intento, por ejemplo `no_frames; intento 1` |
| `recovery_failed` | Motivo y causa: `no se pudo reabrir en 3 intentos`, `sin frames tras 3 recuperaciones` o `lectura congelada; cierre diferido` |

Cuando la recuperación falla, el historial continúa con `client_disconnected` (motivo `recovery_failed`) si había cliente, y `stopped`.

## Límite de una sesión y un cliente

Como la recuperación ocurre dentro del candado, ninguna otra operación puede intervenir mientras tanto. Un segundo cliente o un `start` esperan a que la recuperación termine y reciben `CAMERA_BUSY` o `SESSION_ALREADY_ACTIVE`. La cámara vieja siempre se cierra antes de abrir la nueva, y si la vieja no puede cerrarse porque su lectura sigue congelada, nunca se abre una segunda.

## Configuración

En `app/core/limits.py`:

| Constante | Valor | Uso |
|---|---|---|
| `FRAME_STALE_TIMEOUT_S` | 5.0 | Umbral de estancamiento y margen para que termine una lectura al detener la captura |
| `WATCHDOG_INTERVAL_S` | 0.5 | Cada cuánto revisa el vigilante |
| `RECOVERY_MAX_ATTEMPTS` | 3 | Intentos de reapertura por recuperación, y recuperaciones seguidas sin frames antes de rendirse |
| `RECOVERY_BACKOFF_S` | 0.5 | Espera antes del primer intento; se duplica en cada uno |

Con estos valores, una cámara que no vuelve se declara perdida en unos 10 segundos: 5 s de umbral, hasta 5 s de margen para la lectura en curso y 3.5 s de esperas entre intentos.

## Cambios de contrato

| Antes | Ahora |
|---|---|
| Un frame vacío terminaba la captura con `CAMERA_NO_FRAMES` (cierre 1000) | Un frame vacío cuenta como perdido; tras el umbral se intenta recuperar |
| Un error del driver al leer terminaba con `CAMERA_READ_ERROR` (cierre 1011) | El error cuenta como frame perdido; tras el umbral se intenta recuperar |
| — | Nuevo `CAMERA_STALLED` (cierre 1011): la cámara no se pudo recuperar |
| — | Nuevo estado `recovering` |

Estos cambios afectan las filas de `CAMERA_NO_FRAMES` y `CAMERA_READ_ERROR` del contrato de M01 y del documento de desacople, que M10 reemplaza. La prueba `test_camara_sin_frames_notifica_y_cierra` de `test_stream_decoupling.py` se actualizó a este comportamiento; las demás pruebas del desacople, de M01, M02, M03 y M07 pasan sin cambios.

El frontend no necesita cambios para seguir funcionando: durante una recuperación exitosa simplemente no llegan frames por unos segundos. Puede consultar `state` y `recovery` en `GET /cameras/session` si quiere mostrar un aviso de "reconectando cámara".

## Pruebas

Todas corren sin cámara física: cada apertura entrega una cámara simulada con un comportamiento elegido por la prueba (frames normales, vacíos, error del driver, lectura lenta o congelada), y los tiempos se reducen inyectando parámetros al gestor.

```powershell
cd backend
python -m pytest tests/test_stall_recovery.py -v
```

| Criterio | Pruebas |
|---|---|
| Distingue una cámara activa de una estancada | `test_c1_camara_que_entrega_frames_esta_activa`, `test_c1_frames_vacios_se_detectan_como_no_frames`, `test_c1_lectura_congelada_se_detecta_como_read_timeout`, `test_c1_una_lectura_normal_en_curso_no_se_confunde_con_una_congelada`, `test_c1_un_frame_vacio_aislado_no_cierra_la_conexion`, `test_c1_tambien_se_vigila_sin_cliente` |
| La falta de frames tras el umbral dispara recuperación controlada | `test_c2_recupera_y_el_mismo_cliente_sigue_recibiendo`, `test_c2_recupera_lectura_congelada_que_termina_dentro_del_margen`, `test_c2_reintenta_la_apertura_con_esperas_crecientes`, `test_c2_si_no_logra_reabrir_cierra_y_avisa_camera_stalled`, `test_c2_se_rinde_si_tras_recuperar_sigue_sin_frames`, `test_ws_el_cliente_sobrevive_a_la_recuperacion`, `test_ws_recuperacion_fallida_avisa_camera_stalled_con_1011` |
| La última actividad y el motivo quedan registrados | `test_c3_estado_expone_actividad_y_recuperacion` |
| La recuperación conserva una sesión y un cliente | `test_c4_durante_la_recuperacion_nadie_mas_entra`, `test_c4_lectura_congelada_no_abre_una_segunda_camara`, `test_c4_detener_durante_la_recuperacion_deja_todo_cerrado`, `test_c4_cerrar_la_sesion_no_deja_vigilantes_pendientes` |

Dos defectos se verificaron a propósito: si se quita la regla de no cerrar a mitad de una lectura, o el límite de recuperaciones seguidas, las pruebas correspondientes fallan.

## Demostración funcional

Con una webcam USB y el servidor en marcha (`uvicorn app.main:app --port 8000 --workers 1`):

1. Conecta `ws://localhost:8000/ws/stream?camera_id=0` en Postman. Llegan frames.
2. Consulta `GET /cameras/session`: `state` es `streaming` y `seconds_without_frames` se mantiene cerca de cero.
3. **Desconecta la webcam del USB.** Consulta el estado varias veces: `seconds_without_frames` crece y, pasados unos 5 segundos, `state` cambia a `recovering` y aparece el evento `stalled`.
4. **Recuperación exitosa:** vuelve a conectar la webcam durante la recuperación. Aparece `recovered`, el WebSocket vuelve a recibir frames y `recovery.last_result` es `recovered`.
5. **Recuperación fallida:** repite sin reconectarla. El WebSocket recibe `CAMERA_STALLED`, se cierra con 1011, y el estado vuelve a `idle` con el evento `recovery_failed`.

Al desconectar la webcam, cada driver reacciona distinto: algunos devuelven frames vacíos (`no_frames`) y otros dejan la lectura congelada (`read_timeout`). Cualquiera de los dos queda registrado con su motivo. Si el driver deja la lectura congelada, la recuperación falla por diseño, para no abrir una segunda captura del mismo dispositivo.

## Limitaciones conocidas

- **Imagen negra no es estancamiento.** Se detecta la ausencia de frames, no su contenido. Una cámara tapada entrega frames válidos y se considera activa.
- **Hilos de lectura congelados.** Si el driver nunca devuelve una lectura, ese hilo queda bloqueado y el dispositivo no se cierra hasta que termine; una nueva apertura de la misma cámara puede fallar con `CAMERA_UNAVAILABLE` mientras tanto.
- **La recuperación retiene el candado.** Durante una recuperación (hasta unos 10 s en el peor caso), las demás operaciones esperan su turno.
- **Un solo worker.** Igual que en M03 y M07, la exclusión vive en la memoria del proceso.

## Archivos

| Archivo | Cambio |
|---|---|
| `app/core/limits.py` | Constantes de vigilancia y recuperación |
| `app/services/camera_session_manager.py` | Captura tolerante a frames perdidos, vigilante, clasificación del motivo, recuperación, registro y estado `recovering` |
| `app/services/stream_runner.py` | Código de cierre 1011 para `CAMERA_STALLED` |
| `tests/test_stall_recovery.py` | Nuevas pruebas de M10 |
| `tests/test_stream_decoupling.py` | Actualización de la prueba de cámara sin frames al nuevo comportamiento |
