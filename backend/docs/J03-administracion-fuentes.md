# J03 — Administración de fuentes de video

**Línea:** persistencia · **Orden:** J03 · **Depende de:** J01 (modelo), J02 (sesiones y repositorios), contrato de cámaras aprobado

## Alcance

Crear operaciones para registrar, consultar, actualizar, habilitar y deshabilitar fuentes autorizadas.

## Resumen

J01 definió cómo se guarda una cámara y J02 cómo se consulta. J03 construye encima las operaciones de negocio, en un servicio (`SourceAdminService`) que los routers de una tarea posterior solo tendrán que llamar. El servicio concentra las reglas: qué es un registro válido, cuándo un nombre o una fuente se repiten, qué distingue una fuente deshabilitada de una eliminada, y que nada de lo que entra o sale lleve credenciales.

Como los repositorios, el servicio no hace commit: trabaja sobre la sesión que recibe, y quien la abrió decide cuándo confirmar.

## Operaciones

| Operación | Método | Qué hace |
|---|---|---|
| Registrar | `register(SourceCreate)` | Valida los datos y la unicidad, y crea la fuente en estado `active` |
| Consultar una | `get(id)` | Devuelve la fuente, o `SourceNotFoundError` |
| Listar | `list(status=?, include_retired=?)` | Todas, por estado, o sin las retiradas |
| Actualizar | `update(id, SourceUpdate)` | Cambia nombre, fuente o referencia de credencial |
| Deshabilitar | `disable(id)` | Pasa a `inactive`: registrada, pero fuera de servicio |
| Habilitar | `enable(id)` | Regresa a `active` |
| Retirar | `retire(id)` | Da de baja sin borrar, para conservar el historial |

Los errores llevan un código estable para que la API los traduzca a respuestas: `SOURCE_NOT_FOUND`, `SOURCE_DUPLICATE`, `SOURCE_INVALID_STATE` y los de validación de campo.

## Validación de identidad, estado y datos

**Identidad.** No se repiten ni el nombre ni la fuente (tipo + valor). La comprobación se hace en el servicio y, como segunda línea de defensa, las restricciones únicas de J01 la garantizan en la base. Dos tipos distintos sí pueden compartir el mismo valor: el USB `0` y un archivo llamado `0` son fuentes diferentes.

**Datos.** Cada tipo de fuente tiene su forma: USB es un índice numérico (`0`, `1`...); RTSP debe empezar con `rtsp://` o `rtsps://`; un archivo es cualquier ruta no vacía. `credential_ref` debe ser el nombre de un secreto en mayúsculas (`CAMARA_LINEA1_RTSP`), nunca la credencial.

**Actualización parcial.** `SourceUpdate` usa un centinela `UNSET` para distinguir "no toques este campo" de "ponlo en vacío". Así, actualizar solo el nombre deja intactas la fuente y la credencial, y enviar `credential_ref=""` sí la quita.

## Deshabilitada no es lo mismo que eliminada

Una cámara tiene tres estados, y el criterio pide distinguir los dos últimos:

| Estado | Qué significa | ¿Puede volver? |
|---|---|---|
| `active` | En servicio | — |
| `inactive` | **Deshabilitada**: registrada, pero temporalmente fuera de servicio | Sí, con `enable` |
| `retired` | **Eliminada**: dada de baja de forma definitiva | No |

La diferencia clave es que **ninguna cámara se borra de la base**. En lugar de un `DELETE`, "eliminar" significa `retire`, que marca la cámara como `retired` y conserva su historial de corridas y detecciones. Esto también respeta la regla de J01 de no borrar una cámara con historial.

Al retirar, el nombre y la fuente se renombran (`[retirada] Línea 1 (a1b2c3d4)` y `retired:<id>`), lo que libera esos valores para registrar una cámara nueva sin chocar con la unicidad, sin perder el rastro de cuál fue. Una fuente retirada ya no se modifica ni cambia de estado: cualquier intento devuelve `SOURCE_INVALID_STATE`.

```mermaid
stateDiagram-v2
    [*] --> active: register
    active --> inactive: disable
    inactive --> active: enable
    active --> retired: retire
    inactive --> retired: retire
    retired --> [*]
    note right of retired
        No se borra: conserva
        su historial
    end note
```

## Credenciales

Es la misma regla de todo el sistema: la base guarda la fuente pública y solo el *nombre* del secreto. El servicio la hace cumplir en las dos direcciones:

- **Al entrar:** `register` y `update` rechazan con `SourceValidationError` cualquier fuente que traiga usuario y contraseña (`rtsp://admin:clave@...`) o un parámetro sensible (`?password=...`, `?token=...`), y cualquier `credential_ref` que parezca una credencial en vez de un nombre.
- **Al salir:** la vista pública `SourceRead` expone `has_credentials` (un booleano) y `credential_ref` (un nombre), nunca un secreto. Una prueba recorre todas las respuestas del servicio y la propia fila de la base para confirmar que una contraseña de prueba no aparece en ninguna parte.

## Pruebas

Cada prueba usa una base SQLite en memoria, nueva por caso, y trabaja a través del servicio como lo haría la API.

```powershell
cd backend
python -m pytest tests/test_source_admin.py -v
```

| Criterio | Pruebas |
|---|---|
| Las operaciones validan identidad, estado y datos | `test_c1_*` (registro válido, nombre y fuente duplicados, fuente mal formada, nombre vacío, credential_ref, operar sobre inexistente, actualización total y parcial) |
| Las fuentes deshabilitadas se distinguen de las eliminadas | `test_c2_*` (deshabilitar conserva, habilitar regresa, retirar no borra y es distinto de deshabilitar, retirar libera nombre y fuente, una retirada no se modifica, el listado distingue estados) |
| Las respuestas nunca exponen credenciales | `test_c3_*` (credenciales en la fuente al registrar y al actualizar, la respuesta solo lleva la referencia, ninguna salida ni la base contienen el secreto) |

Se comprobó que las pruebas detectan los fallos reales: si `retire` usara `inactive`, si `register` no revisara la unicidad del nombre, o si no se validaran las credenciales en la fuente, las pruebas correspondientes fallan.

## Demostración reproducible

```powershell
cd backend
python scripts/demo_j03_fuentes.py
```

Sobre una base en memoria, registra tres fuentes (USB, RTSP con credencial y archivo), muestra el listado por estado, actualiza una, la deshabilita y la habilita, retira otra y demuestra que su nombre queda libre, y al final intenta cuatro operaciones inválidas (nombre duplicado, credenciales en la fuente, modificar una retirada, fuente mal formada), mostrando cómo se rechaza cada una. No necesita cámara, modelos ni red.

## Limitaciones y pendientes

- **Sin endpoints todavía.** J03 define el servicio; exponerlo como `POST /sources`, `GET /sources`, etc., es trabajo de la siguiente tarea de la línea.
- **La verificación de que la fuente funciona.** El servicio valida la *forma* de la fuente, no que la cámara responda. Probar la conexión real corresponde al subsistema de cámaras (M01–M12), no a la administración.
- **Resolución de credenciales.** `credential_ref` guarda el nombre del secreto; leerlo del entorno al abrir la cámara es responsabilidad de quien la abre, no de esta capa.
- **Sin control de acceso.** Quién puede registrar o retirar fuentes es un tema de autorización, fuera del alcance de J03.

## Archivos

| Archivo | Contenido |
|---|---|
| `app/services/source_schemas.py` | Esquemas de entrada y salida, validación y centinela `UNSET` |
| `app/services/source_admin.py` | `SourceAdminService` con las operaciones y sus reglas |
| `tests/test_source_admin.py` | Pruebas de J03 |
| `scripts/demo_j03_fuentes.py` | Demostración reproducible |
| `docs/J03-administracion-fuentes.md` | Este documento |
