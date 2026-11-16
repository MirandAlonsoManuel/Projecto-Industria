# J01 — Modelo de datos de cámaras y detecciones

**Línea:** persistencia · **Orden:** J01 · **Depende de:** contratos compartidos de cámaras y detecciones

## Alcance

Definir entidades, relaciones y metadatos para cámaras registradas, eventos de detección y procesamiento.

## Resumen

Hasta ahora el sistema no guardaba nada: las cámaras se identificaban por el texto que mandaba el cliente y las detecciones existían solo mientras viajaban por el WebSocket. J01 define dónde y cómo se conservarán.

El modelo tiene cuatro entidades, de lo general a lo particular: una **cámara** registrada tiene **corridas de procesamiento**; cada corrida produce **eventos de detección**, uno por frame procesado; y cada evento contiene las **detecciones** de ese frame.

La integridad no depende solo del código de Python. Las reglas importantes viven también en la base de datos como llaves foráneas, restricciones únicas y restricciones `CHECK`, de modo que ni un script externo ni una consulta manual puedan dejar datos inconsistentes. Las pruebas lo comprueban insertando con SQL directo.

```mermaid
erDiagram
    cameras ||--o{ processing_runs : "tiene"
    processing_runs ||--o{ detection_events : "produce"
    detection_events ||--o{ detections : "contiene"

    cameras {
        string id PK
        string name UK
        string source_type
        string source
        string credential_ref
        string status
        datetime created_at
        datetime updated_at
    }
    processing_runs {
        string id PK
        string camera_id FK
        string kind
        string model_id
        string status
        datetime started_at
        datetime finished_at
    }
    detection_events {
        string id PK
        string run_id FK
        string camera_id FK
        int frame_seq
        datetime captured_at
    }
    detections {
        string id PK
        string event_id FK
        string label
        float confidence
        float x1
        float y1
        float x2
        float y2
    }
```

## Entidades

Todos los identificadores son UUID4 en texto (36 caracteres), generados por el modelo. Todas las fechas se guardan en UTC y con zona horaria (ver "Fechas").

### `cameras` — cámaras registradas

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | texto (36) | No | Identificador UUID4 |
| `name` | texto (100) | No | Nombre único y legible, por ejemplo "Línea 1" |
| `source_type` | `usb`, `rtsp`, `file` | No | Tipo de fuente |
| `source` | texto (500) | No | Fuente **pública**: índice USB, ruta de archivo o URL RTSP *sin* usuario ni contraseña |
| `credential_ref` | texto (64) | Sí | **Nombre** del secreto con las credenciales (por ejemplo, una variable de entorno `CAMARA_LINEA1_RTSP`); nunca la credencial misma |
| `status` | `active`, `inactive`, `retired` | No | `active` por defecto; `retired` da de baja la cámara sin perder su historial |
| `created_at` | fecha UTC | No | Alta del registro |
| `updated_at` | fecha UTC | No | Última modificación; se actualiza sola |

### `processing_runs` — corridas de procesamiento

Una corrida es una sesión de trabajo sobre una cámara: un stream (`/ws/stream`), un stream con inferencia (`/ws/inference-stream`) o el análisis de una imagen (`/inference/*`).

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | texto (36) | No | Identificador UUID4 |
| `camera_id` | texto (36) | No | Cámara procesada |
| `kind` | `stream`, `inference_stream`, `image` | No | Tipo de procesamiento |
| `model_id` | texto (100) | Sí | Modelo usado; obligatorio con inferencia y vacío en un `stream` |
| `model_version` | texto (50) | Sí | Versión del modelo |
| `parameters` | JSON | No | Parámetros de la corrida: `conf`, `iou`, ROI, `infer_every_n_frames`... Nunca credenciales |
| `status` | `pending`, `running`, `completed`, `failed`, `cancelled` | No | Estado de la corrida |
| `created_at` | fecha UTC | No | Creación |
| `started_at` | fecha UTC | Sí | Inicio real |
| `finished_at` | fecha UTC | Sí | Fin, en estados terminales |
| `frames_processed` | entero | No | Frames procesados (0 por defecto) |
| `error_code` | texto (50) | Sí | Código de la falla (por ejemplo `CAMERA_STALLED`); solo si `status` es `failed` |
| `error_message` | texto (500) | Sí | Descripción de la falla, sin credenciales |

### `detection_events` — eventos de detección

Un evento es el resultado de procesar un frame concreto de una corrida.

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | texto (36) | No | Identificador UUID4 |
| `run_id` | texto (36) | No | Corrida que produjo el evento |
| `camera_id` | texto (36) | No | Cámara del frame; debe coincidir con la de la corrida |
| `frame_seq` | entero | No | Secuencia del frame en la captura (el `seq` del stream) |
| `captured_at` | fecha UTC | No | Momento de captura del frame |
| `processed_at` | fecha UTC | No | Momento en que se terminó de procesar |
| `frame_width` | entero | Sí | Ancho del frame en píxeles |
| `frame_height` | entero | Sí | Alto del frame en píxeles |
| `roi` | JSON | Sí | ROI aplicado, en coordenadas del frame completo: `[[x, y], ...]` |

### `detections` — detecciones

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | texto (36) | No | Identificador UUID4 |
| `event_id` | texto (36) | No | Evento al que pertenece |
| `label` | texto (100) | No | Etiqueta del objeto |
| `class_id` | entero | Sí | Clase numérica del modelo |
| `confidence` | real | No | Confianza entre 0 y 1 |
| `x1` | real | No | Esquina superior izquierda, en píxeles del frame completo |
| `y1` | real | No | Esquina superior izquierda, en píxeles del frame completo |
| `x2` | real | No | Esquina inferior derecha |
| `y2` | real | No | Esquina inferior derecha |
| `attributes` | JSON | Sí | Datos extra del modelo (por ejemplo, texto de OCR). Nunca credenciales |

## Restricciones

Los nombres siguen una convención fija (`ck_` para `CHECK`, `uq_` para únicas, `fk_` para llaves foráneas, `ix_` para índices), para que las migraciones futuras generen siempre los mismos.

### `cameras`

| Restricción | Regla |
|---|---|
| `uq_cameras_name` | No hay dos cámaras con el mismo nombre |
| `uq_cameras_source_type_source` | No hay dos cámaras con la misma fuente |
| `ck_cameras_name_not_blank` | El nombre no puede estar vacío |
| `ck_cameras_source_not_blank` | La fuente no puede estar vacía |
| `ck_cameras_updated_after_created` | `updated_at` no puede ser anterior a `created_at` |
| `ck_cameras_source_type` | Solo valores válidos de `source_type` |
| `ck_cameras_camera_status` | Solo valores válidos de `status` |

### `processing_runs`

| Restricción | Regla |
|---|---|
| `fk_processing_runs_camera_id_cameras` | La cámara debe existir. `ON DELETE RESTRICT`: no se borra una cámara con historial; se retira con `status = retired` |
| `uq_processing_runs_id_camera_id` | Permite que los eventos referencien el par (corrida, cámara) |
| `ck_processing_runs_frames_processed_non_negative` | `frames_processed` ≥ 0 |
| `ck_processing_runs_model_matches_kind` | Un `stream` no tiene modelo; una corrida con inferencia sí |
| `ck_processing_runs_started_matches_status` | `pending` no tiene inicio; `running`, `completed` y `failed` sí; `cancelled` puede tenerlo o no |
| `ck_processing_runs_finished_matches_status` | Solo los estados terminales tienen fecha de fin, y todos la tienen |
| `ck_processing_runs_started_after_created` | El inicio no es anterior a la creación |
| `ck_processing_runs_finished_after_started` | El fin no es anterior al inicio |
| `ck_processing_runs_error_only_when_failed` | Solo una corrida `failed` tiene error, y siempre con código |
| `ck_processing_runs_run_kind` | Solo valores válidos de `kind` |
| `ck_processing_runs_run_status` | Solo valores válidos de `status` |

### `detection_events`

| Restricción | Regla |
|---|---|
| `fk_detection_events_run_id_camera_id_processing_runs` | Llave compuesta: la corrida debe existir **y** la cámara del evento debe ser la de esa corrida. `ON DELETE CASCADE` |
| `uq_detection_events_run_id_frame_seq` | Un solo evento por frame en cada corrida |
| `ck_detection_events_frame_seq_non_negative` | `frame_seq` ≥ 0 |
| `ck_detection_events_processed_after_captured` | No se procesa un frame antes de capturarlo |
| `ck_detection_events_frame_size_positive` | Ancho y alto se informan juntos y son positivos |

### `detections`

| Restricción | Regla |
|---|---|
| `fk_detections_event_id_detection_events` | El evento debe existir. `ON DELETE CASCADE` |
| `ck_detections_label_not_blank` | La etiqueta no puede estar vacía |
| `ck_detections_class_id_non_negative` | `class_id` ≥ 0 cuando existe |
| `ck_detections_confidence_in_range` | Confianza entre 0 y 1 |
| `ck_detections_box_origin_non_negative` | La caja empieza dentro del frame |
| `ck_detections_box_has_area` | `x2 > x1` y `y2 > y1` |

## Índices

Cada índice existe para una consulta concreta; no se agregaron índices "por si acaso", porque cada uno encarece las escrituras.

| Índice | Consulta que acelera |
|---|---|
| `ix_cameras_status` | Listar cámaras activas |
| `ix_processing_runs_camera_id_created_at` | Historial de corridas de una cámara, de la más reciente a la más antigua |
| `ix_processing_runs_status` | Encontrar corridas en curso o fallidas |
| `ix_detection_events_camera_id_captured_at` | Eventos de una cámara en un rango de fechas, la consulta más frecuente de un historial |
| `ix_detections_event_id` | Detecciones de un evento |
| `ix_detections_label` | Buscar todas las apariciones de una etiqueta (por ejemplo, "pieza defectuosa") |

Las restricciones únicas ya crean su propio índice, así que la búsqueda de un frame dentro de una corrida (`uq_detection_events_run_id_frame_seq`) no necesita otro.

## Integridad

**Identificadores.** UUID4 generados por el modelo, nunca por el cliente: no se pueden adivinar ni chocan entre equipos.

**Relaciones.** Las políticas de borrado protegen el historial:

| Si se borra... | ...entonces |
|---|---|
| Una cámara con corridas | Se rechaza. Las cámaras se retiran con `status = retired` |
| Una corrida | Se borran sus eventos y detecciones |
| Un evento | Se borran sus detecciones |

`detection_events.camera_id` repite la cámara de la corrida a propósito, para consultar el historial de una cámara por fecha sin unir tablas. La llave foránea compuesta impide que esa repetición se contradiga.

**Fechas.** La columna `UTCDateTime` rechaza fechas sin zona horaria (una fecha "ingenua" no dice a qué instante real corresponde) y convierte las demás a UTC. Una hora de Guadalajara (UTC−6) se guarda como el mismo instante en UTC y se lee de vuelta con zona.

**Estados.** El estado de una corrida solo debe cambiar con sus métodos, que validan las transiciones:

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: start()
    pending --> cancelled: cancel()
    running --> completed: complete()
    running --> failed: fail(código, mensaje)
    running --> cancelled: cancel()
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

Una transición inválida lanza `InvalidTransitionError` y no modifica nada. Aun si alguien cambiara el estado sin los métodos, las restricciones `CHECK` impiden combinaciones imposibles, como una corrida terminada sin fecha de fin.

## Credenciales

Las cámaras IP suelen llevar usuario y contraseña en la URL. El modelo separa dos cosas:

- **`source`** guarda la fuente pública, por ejemplo `rtsp://10.0.0.5:554/stream`.
- **`credential_ref`** guarda solo el **nombre** del secreto donde viven las credenciales, por ejemplo la variable de entorno `CAMARA_LINEA1_RTSP`. Debe ser un nombre en mayúsculas, de modo que un valor como `admin:clave` se rechaza.

Los campos destinados a respuesta o historial (`source`, `parameters`, `error_message` y `attributes`) pasan por un detector que rechaza con `CredentialLeakError`, antes de llegar a la base:

- usuario o contraseña dentro de una URL (`rtsp://admin:clave@...`);
- parámetros sensibles en una URL (`?password=...`, `?token=...`);
- campos JSON cuyo nombre indica una credencial (`password`, `token`, `secret`, `api_key`, `auth`...) y que contienen texto. Un número, como `"token_count": 3`, no se considera credencial.

## Decisiones técnicas

**SQLAlchemy 2.0.** Es el ORM estándar con FastAPI, y el mismo modelo funciona con SQLite (pruebas y desarrollo) y con PostgreSQL (producción).

**Estados como texto con `CHECK`.** Se guardan como texto legible y no como tipos `ENUM` nativos, que cambian entre motores. La restricción `CHECK` garantiza que solo existan valores válidos.

**Un evento por frame, varias detecciones por evento.** Así se distingue "procesé este frame y no encontré nada" (evento sin detecciones) de "no procesé este frame" (sin evento). Ambas cosas importan para auditar un proceso industrial.

**Coordenadas del frame completo.** Las cajas se guardan en píxeles del frame completo, aunque se haya usado un ROI, igual que las devuelve hoy la API (ver `desacople-captura-websocket.md`). El ROI aplicado queda en `roi` para reconstruir el contexto.

## Pruebas

Cada prueba usa una base SQLite en memoria, nueva y vacía.

```powershell
cd backend
python -m pytest tests/test_data_model.py -v
```

| Criterio | Pruebas |
|---|---|
| Integridad de identificadores | `test_c1_ids_son_uuid_unicos_generados_por_el_modelo`, `test_c1_id_duplicado_se_rechaza`, `test_c1_nombre_y_fuente_de_camara_son_unicos` |
| Integridad de relaciones | `test_c1_relaciones_completas_camara_corrida_evento_deteccion`, `test_c1_corrida_con_camara_inexistente_se_rechaza`, `test_c1_evento_debe_coincidir_con_la_camara_de_su_corrida`, `test_c1_un_frame_solo_tiene_un_evento_por_corrida`, `test_c1_no_se_borra_una_camara_con_historial`, `test_c1_borrar_una_corrida_borra_sus_eventos_y_detecciones` |
| Integridad de fechas | `test_c1_fechas_sin_zona_horaria_se_rechazan`, `test_c1_fechas_se_guardan_en_utc_y_conservan_el_instante`, `test_c1_fin_antes_del_inicio_se_rechaza`, `test_c1_procesado_antes_de_capturado_se_rechaza`, `test_c1_updated_at_avanza_al_modificar` |
| Integridad de estados | `test_c1_ciclo_de_estados_valido`, `test_c1_transiciones_invalidas_se_rechazan`, `test_c1_falla_guarda_codigo_y_mensaje`, `test_c1_la_base_rechaza_estados_inconsistentes`, `test_c1_stream_sin_modelo_e_inferencia_con_modelo`, `test_c1_detecciones_invalidas_se_rechazan` |
| Documentación de campos, restricciones e índices | `test_c2_la_documentacion_cubre_todos_los_campos_restricciones_e_indices` |
| Sin credenciales en respuesta o historial | `test_c3_la_fuente_de_una_camara_no_acepta_credenciales`, `test_c3_la_credencial_se_referencia_por_nombre`, `test_c3_la_corrida_no_acepta_credenciales`, `test_c3_los_atributos_de_una_deteccion_no_aceptan_credenciales`, `test_c3_detector_de_credenciales`, `test_c3_ninguna_tabla_termina_con_secretos` |

La prueba de documentación compara este archivo con el esquema real: si alguien agrega una columna, una restricción o un índice sin documentarlo, falla.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j01_modelo.py
```

Crea una base en memoria, registra una cámara IP sin credenciales, simula una corrida con eventos y detecciones, imprime el historial y luego intenta siete operaciones inválidas (fechas incoherentes, estados imposibles, credenciales en la fuente o en los parámetros...), mostrando cómo se rechaza cada una. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **Validar contra los contratos compartidos.** Los campos de `detections` siguen la forma en que la API devuelve hoy las detecciones de localización. Antes de aceptar J01 debe confirmarse que coinciden con el contrato aprobado de detecciones (`E01_inference_engine_contract.md`) y de cámaras; si el contrato usa otros nombres o formatos, se ajusta aquí.
- **Sin migraciones todavía.** El esquema se crea con `Base.metadata.create_all`. Para producción falta configurar Alembic; la convención de nombres ya está preparada para eso.
- **Reglas entre tablas.** La base no puede comprobar con `CHECK` que una caja quede dentro del ancho del frame o que un evento se capture después del inicio de su corrida, porque involucran otra fila. Esas reglas corresponden a la capa que guarde los datos.
- **Sin integración con la API.** J01 define el modelo; guardar las corridas y detecciones desde los WebSocket es trabajo de las siguientes tareas de la línea de persistencia.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/db/__init__.py` | Exportaciones de la capa de persistencia |
| `app/db/base.py` | `Base`, convención de nombres, `UTCDateTime` y `create_db_engine` |
| `app/db/models.py` | Entidades, restricciones, índices, transiciones y detector de credenciales |
| `tests/test_data_model.py` | Pruebas de J01 |
| `scripts/demo_j01_modelo.py` | Demostración reproducible |
| `docs/J01-modelo-de-datos.md` | Este documento |
| `requirements.txt` | Nueva dependencia: `sqlalchemy` |
