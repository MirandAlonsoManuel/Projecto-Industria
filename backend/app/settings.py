from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FastAPI Inference API"
    version_api: str = "0.1.0"
    model_path: str = "models/model.pkl"

    model_name: str = "model.pkl"
    model_version: str = "1.0.0"

    config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")