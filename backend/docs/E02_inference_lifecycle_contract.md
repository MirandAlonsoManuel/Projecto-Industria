# [E02][P1] Carga única y cierre ordenado del modelo

**Responsable:** Manuel Miranda
**Módulo:** `app/services/inference_lifecycle.py`
**Depende de:** E01 (`app/services/inference_engine.py`)

---

## 1. Estados y transiciones

| Estado | Significado | Se llega desde | Se sale hacia |
|---|---|---|---|
| `NOT_INITIALIZED` | Estado inicial; nunca se llamó `initialize()` | (inicio) | `LOADING` vía `initialize()` |
| `LOADING` | `engine.load()` en curso | `NOT_INITIALIZED` o `ERROR`, vía `initialize()` | `AVAILABLE` (éxito) o `ERROR` (falla/cancelación) |
| `AVAILABLE` | Motor cargado, listo para `predict()` | `LOADING` | `CLOSED` vía `shutdown()` |
| `ERROR` | La carga falló o fue cancelada; causa en `last_error` | `LOADING` | `LOADING` (reintento vía `initialize()`) o `CLOSED` vía `shutdown()` |
| `CLOSED` | Terminal; recursos liberados | `AVAILABLE` o `ERROR`, vía `shutdown()` | ninguno — es terminal para esa instancia |

Diagrama de transición completo adjunto en el PR (o disponible bajo pedido): `NOT_INITIALIZED → LOADING → AVAILABLE → CLOSED` como camino feliz, con `LOADING → ERROR` ante falla o cancelación, `ERROR → LOADING` como reintento, y `ERROR → CLOSED` como salida alternativa.

Nota importante: este estado es **distinto** de `EngineState` (E01), que describe solo al motor (`unloaded` / `loaded` / `error`). `LifecycleState` agrega dos fases que la aplicación necesita y que el motor no expone por sí solo: la transición `LOADING` (útil para que un health-check sepa que el arranque está en curso, no caído) y el estado terminal `CLOSED` (distingue "nunca se inicializó" de "se cerró a propósito").

## 2. Garantía de carga única

`initialize()` está protegido por un `asyncio.Lock`. Si ya está `AVAILABLE`, retorna de inmediato sin tocar el motor — esto cubre tanto llamadas repetidas secuenciales como **concurrentes**: si dos corrutinas llaman `initialize()` al mismo tiempo, la segunda espera el lock y, al obtenerlo, ve que el estado ya es `AVAILABLE` y no vuelve a invocar `engine.load()`. Verificado explícitamente con una prueba que cuenta invocaciones reales a `load()` bajo `asyncio.gather()`.

## 3. Cierre: idempotente, ante error, ante cancelación

`shutdown()` también está protegido por el lock. Si ya está `CLOSED`, es un no-op. Se probó explícitamente que puede cerrarse correctamente:
- en operación normal (desde `AVAILABLE`),
- después de una carga fallida (desde `ERROR`),
- después de una `initialize()` cancelada a mitad de carga (el `except asyncio.CancelledError` dentro de `initialize()` ya deja el estado en `ERROR` y cierra defensivamente el motor antes de re-lanzar la cancelación).

La limpieza del motor (`engine.close()`) se ejecuta dentro de un `try/except` propio (`_safe_close_engine`) para que una falla al cerrar no oculte la causa original del error de carga, ni impida que el estado quede correctamente marcado.

## 4. Decisión: ¿`ERROR` permite reintentar?

Sí — `initialize()` llamado en estado `ERROR` reintenta la carga, no lanza de inmediato. El ticket no lo exige explícitamente, pero sin esto la única forma de recuperarse de un error sería descartar la instancia y crear una nueva, lo cual complica la integración con el lifespan de FastAPI (el objeto vive una sola vez por proceso). `CLOSED`, en cambio, sí es terminal a propósito: una vez que la aplicación decide cerrar el motor (shutdown ordenado), reabrirlo silenciosamente podría ocultar un cierre que se esperaba fuera definitivo. Para volver a operar tras un `CLOSED`, se crea una nueva instancia — cubierto explícitamente en las pruebas de "reinicio".

## 5. Integración con `app/main.py`

Se agregó un `lifespan` a `create_app()` (antes inexistente — se confirmó la versión actual de `main.py` antes de tocarla) que:

- En el arranque: crea una `InferenceEngineLifecycle(SimulatedInferenceEngine())`, la guarda en `app.state.inference_lifecycle`, y llama `await lifecycle.initialize()`.
- En el cierre: llama `await lifecycle.shutdown()` dentro de un `try/finally`, para que se ejecute incluso si algo falla durante la vida de la aplicación.

**Decisión explícita:** si `initialize()` falla en el arranque, la excepción se deja propagar — la aplicación completa falla al iniciar, en vez de arrancar en un modo degradado con el estado en `ERROR`. Es la opción más simple y seguridad por defecto para esta entrega; si el equipo prefiere modo degradado, es una decisión de producto a confirmar con el líder técnico, no algo que este ticket decidiera unilateralmente.

**Explícitamente fuera de alcance:** igual que en E01, no se conecta esto con `inference_service.py` ni con `ModelRegistry`. El motor que envuelve esta clase sigue siendo, para efectos de este ticket, `SimulatedInferenceEngine` — conectar un motor real es trabajo de una tarea posterior.

## 6. Pruebas (`tests/test_inference_lifecycle.py`)

Cubren, todas con `SimulatedInferenceEngine` (ningún modelo real, ninguna cámara):

- Inicialización correcta y transición de estado.
- Inicios repetidos **secuenciales y concurrentes** (`asyncio.gather`) — `load()` se invoca exactamente una vez en ambos casos.
- Carga fallida: transición a `ERROR`, causa registrada, y el motor subyacente queda sin recursos (`UNLOADED`).
- Reintento exitoso tras un error.
- Cierre idempotente sin haber inicializado, y llamado dos veces tras inicializar.
- Cierre después de un error.
- Cancelación durante `initialize()`: transición a `ERROR` y cierre posterior exitoso.
- `initialize()` después de `CLOSED` lanza `RuntimeError`.
- Reinicio con una nueva instancia, independiente de una anterior ya cerrada.

Además, `tests/test_app_lifespan.py` prueba de integración: la aplicación completa (`create_app()`) arranca y se detiene disparando el `lifespan` real de `app/main.py`, confirmando que el motor simulado queda `AVAILABLE` durante la vida de la app y `CLOSED` al salir — sin modificar ningún router existente.
