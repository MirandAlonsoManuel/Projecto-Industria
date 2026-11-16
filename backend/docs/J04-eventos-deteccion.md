# J04 — Persistir y consultar eventos de detección

**Línea:** persistencia · **Orden:** J04 · **Depende de:** J01 (modelo), J02 (sesiones y repositorios); contratos E05 y E06 del modelo de detección

## Alcance

Crear operaciones para almacenar y consultar eventos con filtros por cámara, clase, confianza y periodo.

## Resumen

J01 definió la tabla de eventos de detección y J02 cómo acceder a ella. J04 construye encima las dos operaciones que el sistema necesita, reunidas en `DetectionStoreService`:

1. **Guardar** un evento con sus detecciones, validado contra el modelo aprobado.
2. **Consultar** eventos con filtros combinables por cámara, clase, confianza y periodo, con paginación.

Como el resto de la capa, el servicio no hace commit: trabaja sobre la sesión que recibe.

## Guardar un evento

`save_event(DetectionEventInput)` hace tres cosas antes de guardar:

1. **Valida** el evento y cada detección contra el modelo aprobado: etiqueta no vacía, confianza entre 0 y 1, caja con área (`x2 > x1`, `y2 > y1`) y dentro del frame, fechas con zona horaria, procesamiento no anterior a la captura. Un dato inválido da un `DetectionValidationError` con el campo señalado, en vez de un fallo críptico de la base.
2. **Resuelve la cámara desde la corrida.** El `camera_id` del evento se toma de la corrida (`run.camera_id`), no de un valor enviado por fuera. Así es imposible que un evento quede atribuido a una cámara distinta a la de su corrida, que es justo lo que protege la llave foránea compuesta de J01.
3. **Rechaza duplicados.** Un segundo evento para el mismo frame de la misma corrida da `DuplicateEventError`, en línea con la restricción única de J01.

Un evento puede tener cero detecciones: significa "procesé este frame y no encontré nada", distinto de "no procesé este frame" (que no genera evento). Ambos casos importan para auditar un proceso industrial.

## Consultar con filtros

`query(EventQuery)` combina filtros opcionales, todos unidos con Y:

| Filtro | Efecto |
|---|---|
| `camera_id`, `run_id` | Igualdad exacta |
| `start`, `end` | Por fecha de captura: inicio inclusivo, fin **exclusivo** |
| `label` | El evento tiene al menos una detección con esa etiqueta |
| `class_id` | El evento tiene al menos una detección de esa clase |
| `min_confidence` | El evento tiene al menos una detección con esa confianza o más |

Los resultados se ordenan por fecha de captura descendente (lo más reciente primero) y se paginan con `limit` (1 a 1000, 100 por defecto) y `offset`. La respuesta incluye el total de coincidencias y un `has_more` para saber si hay más páginas.

### Una decisión importante sobre el filtro de detecciones

Cuando se filtra por clase, etiqueta o confianza, el filtro decide qué **eventos** aparecen: un evento califica si tiene *al menos una* detección que cumple. Pero cada evento devuelto trae **todas** sus detecciones, no solo las que pasaron el filtro.

Por ejemplo, un evento con una detección de confianza 0.95 y otra de 0.60, consultado con `min_confidence >= 0.9`, aparece en los resultados con **ambas** detecciones. La razón: el evento representa un frame completo, y mostrar solo parte de sus detecciones daría una imagen falsa de lo que había en ese frame. El filtro sirve para encontrar los frames relevantes, no para recortar su contenido.

En SQL, esto se implementa con un `EXISTS` correlacionado sobre las detecciones, que además evita duplicar el evento cuando varias de sus detecciones cumplen el filtro.

## Integridad de las relaciones

El criterio 3 pide que cámara, detección y metadatos conserven integridad, y J04 se apoya en lo que J01 ya garantiza:

- La cámara del evento siempre es la de su corrida (se resuelve en el servicio y lo refuerza la llave foránea compuesta).
- Las detecciones se guardan ligadas a su evento; borrar el evento borra sus detecciones en cascada, pero no la corrida ni la cámara.
- Los metadatos del frame (tamaño, ROI) y los atributos de cada detección (por ejemplo, el texto de OCR) se conservan tal cual se guardaron.

## Pruebas

Cada prueba usa una base SQLite en memoria, nueva por caso, a través del servicio.

```powershell
cd backend
python -m pytest tests/test_detection_store.py -v
```

| Criterio | Pruebas |
|---|---|
| Los eventos cumplen el modelo aprobado | `test_c1_*` (guardar con detecciones, evento vacío válido, detección inválida, evento inválido, fecha sin zona, procesado antes de capturado) |
| Los filtros producen resultados correctos | `test_c2_*` (sin filtros ordenado, por cámara, clase, etiqueta, confianza, periodo, combinados, el evento conserva todas sus detecciones, paginación, sin resultados, parámetros inválidos, periodo invertido) |
| Las relaciones conservan integridad | `test_c3_*` (cámara tomada de la corrida, corrida inexistente, frame sin dos eventos, detecciones ligadas al evento, borrado en cascada, metadatos conservados) |

Se comprobó que las pruebas detectan los fallos reales: si se ignora el filtro de detecciones, si no se rechazan los eventos duplicados, o si el fin del periodo fuera inclusivo en vez de exclusivo, las pruebas correspondientes fallan.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j04_eventos.py
```

Sobre una base en memoria, crea dos cámaras con sus corridas, guarda varios eventos con detecciones de distintas clases, confianzas y horas, y luego ejecuta cada filtro (por cámara, clase, confianza, periodo y combinados), mostrando cuántos eventos devuelve cada uno y cómo un evento filtrado por confianza conserva todas sus detecciones. Termina intentando guardar un evento inválido y uno duplicado, mostrando cómo se rechazan. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **Sin endpoints todavía.** J04 define el servicio; exponerlo como `GET /events?camera=...&class=...` y conectarlo al guardado desde los WebSocket es trabajo de las siguientes tareas.
- **Paginación por offset.** Funciona bien para historiales de tamaño moderado. Para volúmenes muy grandes, una paginación por cursor (sobre `captured_at`) sería más eficiente; se puede añadir sin cambiar el modelo.
- **Sin agregaciones.** J04 devuelve eventos, no resúmenes (conteos por hora, por clase, etc.). Esas consultas analíticas son una tarea aparte; el repositorio de J02 ya trae un `count_by_label_for_run` como base.
- **Zona horaria de los filtros.** Las fechas de los filtros deben traer zona horaria; se convierten a UTC para comparar, igual que se guardan.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/detection_schemas.py` | Esquemas de entrada, filtro y salida, con validación |
| `app/services/detection_store.py` | `DetectionStoreService`: guardar y consultar con filtros |
| `tests/test_detection_store.py` | Pruebas de J04 |
| `scripts/demo_j04_eventos.py` | Demostración reproducible |
| `docs/J04-eventos-deteccion.md` | Este documento |
