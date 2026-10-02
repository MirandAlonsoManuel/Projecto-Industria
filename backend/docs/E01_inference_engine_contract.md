# [E01][P1] Interfaz común para motores de inferencia

**Responsable:** Manuel Miranda
**Módulo:** `app/services/inference_engine.py`

---

## 1. Decisión de diseño principal: una interfaz, no cuatro

El código existente (`inference_service.py`) maneja cuatro tareas con formas de entrada/salida distintas: localización (detecciones + bbox), clasificación (predicciones top-k), OCR (texto + polígono) y anomalía (score + regiones). Se evaluaron dos caminos:

- **(a)** Una interfaz por tarea (`LocalizationEngine`, `ClassificationEngine`, ...).
- **(b)** Una interfaz única y genérica, con un resultado envolvente (`InferenceResult`) cuyo campo `items` cambia de significado según `task`.

Se eligió **(b)** a partir del enunciado del ticket. Es lo que pide el ticket literalmente ("la interfaz", singular) y mantiene el motor simulado mínimo — con 4 interfaces habría que simular 4 contratos distintos para cubrir el mismo criterio de aceptación.

**Trade-off asumido:** `InferenceResult.items` es `list[dict[str, Any]]`, no un tipo fuertemente tipado por tarea. Se documentó explícitamente en el docstring de `InferenceResult` qué claves esperar según `task`, y se escogió esta forma porque **ya es la convención existente** en `InferenceService` (`localize`, `classify`, `ocr`, `anomaly_reference` ya retornan `list[dict[str, Any]]`) — así, una futura integración no tiene que inventar un mapeo nuevo entre lo que ya existe y la interfaz.

## 2. Las cuatro responsabilidades separadas

| Método | Responsabilidad | Reglas de contrato |
|---|---|---|
| `load()` | Cargar pesos/recursos del backend | Idempotente: llamarlo ya cargado no recarga ni falla |
| `predict(frame, **params)` | Ejecutar una predicción | Lanza `EngineNotLoadedError` si no está cargado; `EnginePredictionError` ante entrada inválida o fallo del backend |
| `get_status()` | Consultar estado actual | Nunca lanza; válido en cualquier estado |
| `close()` | Liberar recursos | Idempotente: cerrar ya cerrado (o nunca cargado) no falla |

## 3. Tipos del contrato

- **Entrada:** `np.ndarray` — el mismo tipo que devuelve `image_service.decode_image`, confirmado antes de fijar la firma. No se introduce ningún wrapper propio de frame.
- **Salida:** `InferenceResult` (dataclass congelado): `task`, `model_id`, `items`, `score` (opcional, solo `anomaly`), `latency_ms`.
- **Estado:** `EngineState` (enum: `UNLOADED`, `LOADED`, `ERROR`) + `EngineStatus` (dataclass congelado con `state`, `model_id`, `task`, `loaded_at`, `last_error`).
- **Errores:** jerarquía propia bajo `InferenceEngineError` — `EngineLoadError`, `EngineNotLoadedError`, `EnginePredictionError`. Ninguna excepción cruda de un backend real (ultralytics, torch, etc.) debería escapar de `predict()`/`load()` sin envolverse en estos tipos (responsabilidad de cada implementación concreta, no de esta interfaz).

Sin dependencias externas más allá de NumPy y la librería estándar (`abc`, `dataclasses`, `enum`, `time`, `typing`) — ninguna de pydantic, ultralytics, torch, etc.

## 4. Motor simulado (`SimulatedInferenceEngine`)

Implementación mínima y determinista de `InferenceEngine`, **exclusiva para pruebas automatizadas**. No debe usarse en producción ni registrarse en `ModelRegistry`. Permite forzar un fallo de carga (`fail_on_load=True`) para ejercitar el camino de error sin mockear excepciones a mano en cada prueba.

## 5. Explícitamente fuera de alcance de este ticket

- **No se modificó `inference_service.py`.** Esta interfaz es nueva e independiente; `InferenceService` sigue con su propio despacho de backends por `if/elif`. Conectar ambos (que un motor real implemente `InferenceEngine` y que `InferenceService` lo consuma) es trabajo de una tarea posterior, no de E01.
- **No se tocó `app/schemas/inference.py` ni el router `inference.py`.** El criterio de aceptación exige explícitamente que el motor pueda sustituirse sin cambiar a los consumidores — como no se integró todavía, los consumidores actuales no se tocan en absoluto.

## 6. Pruebas (`tests/test_inference_engine.py`)

Cubren, todas usando `SimulatedInferenceEngine` (ningún modelo real, ninguna cámara):

- Carga correcta y transición de estado.
- `load()` idempotente.
- Predicción simulada con resultado tipado (`InferenceResult`), incluyendo el caso particular de `score` para `task="anomaly"`.
- Consulta de estado en cada fase del ciclo de vida.
- Cierre idempotente (sin haber cargado, y llamado dos veces tras cargar).
- Uso inválido: `predict()` antes de `load()`, y `predict()` después de `close()`.
- Casos adicionales no pedidos explícitamente pero que refuerzan el contrato de errores: frame inválido (`EnginePredictionError`) y fallo de carga (`EngineLoadError` + transición a `ERROR`).
