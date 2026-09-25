# FastAPI Inference API

API REST construida con **FastAPI** para servir modelos de machine learning.

---

## Requisitos previos

- Python 3.10+
- pip

---

## Instalación y arranque

```bash
# 1. Clonar el repositorio
git clone <url-del-repositorio>
cd Projecto-Industria

# 2. Crear y activar el entorno virtual
python -m venv env
source env/bin/activate        # macOS / Linux
env\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install fastapi uvicorn pydantic-settings

# 4. Copiar variables de entorno
cp .env.example .env           # edita .env con tus valores reales

# 5. Levantar el servidor
uvicorn app.main:app --reload
```

El servidor queda disponible en `http://127.0.0.1:8000`.  
Documentación interactiva: `http://127.0.0.1:8000/docs`

---

## Endpoints disponibles

| Método | Ruta      | Descripción                          |
|--------|-----------|--------------------------------------|
| GET    | `/signal` | Verifica que la API está en línea    |

### GET `/signal`

**Respuesta exitosa `200 OK`**

```json
{
  "connected": true
}
```

---

## Probar la API con clientes REST

### Bruno

> Cliente de escritorio open-source. Descarga en [usebruno.com](https://www.usebruno.com)

1. Abre Bruno y crea una **New Collection** llamada `Inference API`.
2. Dentro de la colección, haz clic en **New Request**.
3. Configura:
   - **Method:** `GET`
   - **URL:** `http://127.0.0.1:8000/signal`
4. Presiona **Send**.
5. Deberías ver en el panel de respuesta:

```json
{
  "connected": true
}
```

> Puedes guardar la colección en la carpeta `bruno/` del repo para compartirla con el equipo.

---

### Thunder Client (VS Code)

> Extensión gratuita de VS Code. Instálala desde el Marketplace buscando **Thunder Client**.

1. Abre el panel de Thunder Client en la barra lateral de VS Code.
2. Haz clic en **New Request**.
3. Configura:
   - **Method:** `GET`
   - **URL:** `http://127.0.0.1:8000/signal`
4. Haz clic en **Send**.
5. La respuesta aparece en el panel derecho:

```json
{
  "connected": true
}
```

> Usa **Collections → New Collection** para agrupar todas las peticiones del proyecto y exportarlas como JSON.

---

### YAAK

> Cliente moderno multiplataforma. Descarga en [yaak.app](https://yaak.app)

1. Abre YAAK y crea un **New Workspace** llamado `Inference API`.
2. Dentro del workspace, haz clic en **+** para crear una nueva petición.
3. Configura:
   - **Method:** `GET`
   - **URL:** `http://127.0.0.1:8000/signal`
4. Presiona **Send**.
5. Verifica la respuesta:

```json
{
  "connected": true
}
```

> YAAK permite definir **variables de entorno** por workspace. Crea una variable `base_url = http://127.0.0.1:8000` y úsala como `{{base_url}}/signal` para cambiar el host fácilmente entre local, staging y producción.

---

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto basándote en `.env.example`:

```env
APP_NAME=FastAPI Inference API
VERSION_API=0.1.0
MODEL_PATH=models/model.pkl
MODEL_NAME=model.pkl
MODEL_VERSION=1.0.0
```

---

## Estructura del proyecto

```
Projecto-Industria/
├── app/
│   ├── main.py                  # Punto de entrada de la aplicación
│   ├── core/
│   │   └── config.py            # Configuración centralizada
│   └── api/
│   │    └── routers/
│   │        ├── health.py        # Endpoint /signal
│   │        └── inference.py     # Endpoints de inferencia (en desarrollo)
│   │        └── camera.py        # Endpoints de cámaras
│   │        └── stream.py        # Endpoints de stream
│   └── services/
│        └── camera_registry.py (gestión de sesiones de cámaras)
│─── tests/
│         ├── test_camera_registry.py (pruebas para camera_registry.py)
│         └── manual/
│                └──  test_reject_second_client.py (prueba de que no pueden conectarse 2 clientes a una misma cámara)
├── .env.example                 # Plantilla de variables de entorno
├── .gitignore
└── README.md
```
