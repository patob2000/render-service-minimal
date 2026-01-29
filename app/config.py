"""
Configuración del servicio de renderizado de video
"""
from pydantic_settings import BaseSettings
from typing import Literal
from functools import lru_cache


class Settings(BaseSettings):
    """Configuración con validación automática via Pydantic"""
    
    # Entorno
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = True
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 10000
    api_key: str | None = None
    cors_origins: str = "*"
    
    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    # Storage
    storage_type: Literal["local", "s3"] = "local"
    temp_dir: str = "./temp"
    output_dir: str = "./output"
    
    # AWS S3 (opcional)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    aws_s3_bucket: str | None = None
    
    # FFmpeg
    ffmpeg_path: str | None = None
    
    # Límites
    max_concurrent_jobs: int = 2
    job_timeout_seconds: int = 600  # 10 minutos
    max_slides_per_job: int = 50
    
    # Output settings
    default_resolution: str = "1080p"
    default_fps: int = 30
    default_quality: str = "high"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Singleton de configuración con caché"""
    return Settings()


# Resoluciones disponibles
RESOLUTIONS = {
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}

# CRF para calidad (menor = mejor calidad, mayor archivo)
QUALITY_CRF = {
    "high": 18,
    "medium": 23,
    "low": 28,
}
