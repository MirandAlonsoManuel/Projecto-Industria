# M03 — Acceso exclusivo a la cámara

**Ticket:** OMC-84 · **Secuencia:** M03 · 

## Alcance

Garantizar que la única cámara configurada se abra una sola vez y que la use un solo cliente a la vez. No se requiere distribuir frames ni compartir la captura entre varios clientes.

## Cómo funciona

Todo acceso al hardware pasa por un único gestor, `CameraSessionManager` (`app/services/camera_session_manager.py`), que se expone como la instancia global `camera_session_manager`. El gestor protege con un mismo `asyncio.Lock` las cuatro operaciones que tocan el dispositivo: abrir (`acquire`), cerrar (`release`), apagar (`shutdown`) y escanear (`scan_cameras`).

Cuando un cliente se conecta al WebSocket `/ws/stream`, el router pide la sesión al gestor. Si la cámara está libre, el gestor la abre y la asigna a ese cliente con un identificador único. Si ya está ocupada, el gestor responde de inmediato con `SessionBusyError`, sin abrir hardware y sin tocar la sesión activa. Cuando el cliente se desconecta, el bloque `finally` del router libera la sesión, pase lo que pase durante la transmisión.

## Contrato para los clientes

**Conexión aceptada** (primer mensaje, JSON):

```json
{"connected": true, "camera_id": "0", "error": null, "description": "Cámara detectada. Iniciando transmisión de video."}
```

**Conexión rechazada** (primer mensaje, JSON, seguido del cierre):

| `error` | Código de cierre | Significado |
|---|---|---|
| `CAMERA_BUSY` | 1008 | Otro cliente está usando la cámara. El cliente activo no se ve afectado. |
| `CAMERA_UNAVAILABLE` | 1000 | La fuente no pudo abrirse o el driver falló al abrirla. |
| `CAMERA_NO_FRAMES` | 1000 | La cámara dejó de entregar frames durante la transmisión. |

**Endpoints REST relacionados:**

- `GET /cameras/session`: estado del gestor (`idle` o `streaming`, cliente activo, métricas y errores).
- `GET /cameras`: escanea cámaras USB. La cámara en uso se reporta como `"status": "in_use"` **sin volver a abrirla**.

## Decisiones técnicas y riesgos atendidos

**Aperturas duplicadas por concurrencia.** La verificación de "¿está libre?" y la apertura ocurren dentro del mismo candado, por lo que dos conexiones simultáneas no pueden abrir la cámara dos veces.

**Escaneo que abría la cámara en uso.** Antes, `GET /cameras` sondeaba todos los índices USB, incluido el que estaba transmitiendo, lo que equivalía a una apertura duplicada. Ahora el escaneo corre dentro del candado y excluye la cámara activa.

**Liberación tardía de una conexión vieja.** `release` solo actúa si quien libera es el titular actual. Una conexión antigua que libera tarde no puede cerrar la sesión de una conexión nueva. La operación es idempotente.

**Fallo del driver al cerrar.** La sesión se marca libre antes de cerrar la captura, y los errores del driver se registran en el log sin propagarse. La cámara nunca queda "secuestrada" por un cierre fallido.

**Fallo del driver al abrir.** Cualquier excepción de `open_camera` se convierte en `SessionCameraError` y no deja sesión registrada. Además, `open_camera` libera el objeto de OpenCV cuando la fuente no llega a abrirse.

**Cancelación a mitad de una operación.** Las operaciones de hardware corren en un hilo. Si la tarea que espera se cancela, el gestor no suelta el candado hasta que el hilo termina, y si el hilo alcanzó a abrir una captura que ya nadie usará, la cierra. Así, una cancelación no deja capturas huérfanas ni permite que una apertura nueva se solape con una que aún no concluye.

**Liberación si falla el primer mensaje.** El envío del mensaje de bienvenida quedó dentro del bloque protegido por `finally`, de modo que la cámara se libera aunque el cliente se desconecte antes de recibirlo.

## Pruebas

Las pruebas corren sin cámara física: `open_camera` se reemplaza por una cámara simulada que cuenta aperturas, cierres e instancias abiertas al mismo tiempo.

```powershell
cd backend
python -m pytest -v
```

| Criterio | Pruebas |
|---|---|
| C1 · Una instancia de captura y una sesión | `test_c1_*` |
| C2 · Segundo cliente con error controlado, sin afectar al activo | `test_c2_*`, `test_ws_segundo_cliente_rechazado_y_primero_sigue_transmitiendo` |
| C3 · Al desconectarse, sesión y recurso disponibles | `test_c3_*`, `test_ws_desconexion_libera_para_un_nuevo_cliente` |
| C4 · Sin aperturas duplicadas en concurrencia | `test_c4_*` (20 clientes simultáneos; 8 clientes en ciclos de adquirir y liberar) |

La suite no requiere `pytest-asyncio`: las corrutinas se ejecutan con `asyncio.run` y las pruebas de WebSocket usan el `TestClient` de FastAPI.

## Demostración sin cámara física

`open_camera` acepta la ruta de un archivo de video como fuente, lo que permite demostrar el comportamiento sin hardware.

1. Inicia el servidor con un solo worker.
2. En Postman, abre una conexión WebSocket a `ws://HOST:PUERTO/ws/stream?camera_id=RUTA_A_UN_VIDEO.mp4`. Recibe `connected: true` y luego frames binarios.
3. Abre una segunda conexión WebSocket con la misma URL. Recibe `error: CAMERA_BUSY` y se cierra con 1008, mientras la primera sigue recibiendo frames.
4. Consulta `GET /cameras/session`: muestra `streaming` y el cliente activo.
5. Cierra la primera conexión y vuelve a consultar: muestra `idle`.
6. Conecta de nuevo: la conexión se acepta.

## Limitaciones conocidas

- **Un solo worker.** El candado vive en la memoria del proceso. Con varios workers de uvicorn, cada proceso tendría su propio gestor y la exclusión dejaría de ser real.
- **El escaneo espera a las operaciones en curso.** Mientras `GET /cameras` sondea dispositivos, una conexión nueva espera a que termine (en Windows puede tardar alrededor de 2 segundos).

## Fuera del alcance de M03

Estos puntos del dictamen técnico anterior no forman parte de los criterios de M03 y quedan para las tareas correspondientes: tarea de captura independiente del WebSocket, política explícita de último frame, métricas operativas completas (reconexiones, última actividad), configuración validada de FPS y timeouts, y endpoints explícitos de inicio y detención.
