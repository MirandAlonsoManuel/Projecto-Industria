"""
Configuración centralizada de la aplicación.

Las variables se resuelven en este orden de prioridad (mayor a menor):
  1. Variables de entorno del sistema operativo.
  2. Archivo .env en la raíz del proyecto.
  3. Valores por defecto definidos en la clase Settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Esquema de configuración de la aplicación.

    Cada atributo puede sobrescribirse mediante una variable de entorno
    con el mismo nombre en mayúsculas (p. ej. APP_NAME, VERSION_API).
    """

    # Metadatos generales del servicio
    app_name: str = "FastAPI Inference API"
    version_api: str = "0.1.0"

    # Ruta y metadatos del modelo de machine learning
    model_path: str = "models/model.pkl"
    model_name: str = "model.pkl"
    model_version: str = "1.0.0"

    # Streaming y cámaras
    jpeg_quality: int = 70
    ws_max_queue_size: int = 5
    max_cameras: int = 4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Retorna la instancia única de Settings (patrón singleton vía caché).

    El decorador lru_cache garantiza que el archivo .env se lea una sola vez
    durante el ciclo de vida del proceso, evitando I/O redundante en cada
    solicitud entrante.

    Returns:
        Settings: Objeto de configuración inmutable y reutilizable.
    """
    return Settings()
