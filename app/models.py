"""
Modelos Pydantic para validación de datos
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Optional
from datetime import datetime
from enum import Enum


class SlideType(str, Enum):
    PORTADA = "Portada"
    CONTENIDO = "Contenido"
    CIERRE = "Cierre"


class Resolution(str, Enum):
    HD_1080 = "1080p"
    HD_720 = "720p"
    SD_480 = "480p"


class Quality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SlideData(BaseModel):
    """Datos de una diapositiva para renderizar"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    index: int = Field(..., ge=0, description="Índice de la diapositiva")
    type: SlideType = Field(..., description="Tipo de diapositiva")
    titulo: str = Field(default="", description="Título de la diapositiva")
    background_image: str = Field(..., alias="backgroundImage", description="URL o base64 de la imagen de fondo")
    avatar_video: Optional[str] = Field(None, alias="avatarVideo", description="URL del video de avatar")
    audio_narration: Optional[str] = Field(None, alias="audioNarration", description="URL o base64 del audio")
    duration: Optional[float] = Field(None, gt=0, description="Duración manual en segundos")


class OutputSettings(BaseModel):
    """Configuración de salida del video"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    resolution: Resolution = Field(default=Resolution.HD_1080, description="Resolución del video")
    fps: Literal[24, 30, 60] = Field(default=30, description="Frames por segundo")
    quality: Quality = Field(default=Quality.HIGH, description="Calidad de compresión")


class RenderJobRequest(BaseModel):
    """Request para iniciar un trabajo de renderizado"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    project_id: str = Field(..., alias="projectId", min_length=1, description="ID del proyecto")
    project_name: str = Field(..., alias="projectName", min_length=1, description="Nombre del proyecto")
    slides: list[SlideData] = Field(..., min_length=1, max_length=50, description="Diapositivas a renderizar")
    output_settings: OutputSettings = Field(default_factory=OutputSettings, alias="outputSettings")
    callback_url: Optional[str] = Field(None, alias="callbackUrl", description="Webhook para notificación")


class RenderPhase(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    RENDERING = "rendering"
    CONCATENATING = "concatenating"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class RenderProgress(BaseModel):
    """Progreso del renderizado"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    phase: RenderPhase = Field(..., description="Fase actual")
    current_slide: Optional[int] = Field(None, alias="currentSlide", ge=0)
    total_slides: Optional[int] = Field(None, alias="totalSlides", ge=1)
    percent_complete: float = Field(..., alias="percentComplete", ge=0, le=100)
    message: Optional[str] = Field(None, description="Mensaje de estado")


class RenderResult(BaseModel):
    """Resultado del renderizado exitoso"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    download_url: str = Field(..., alias="downloadUrl", description="URL de descarga")
    expires_at: datetime = Field(..., alias="expiresAt", description="Fecha de expiración")
    file_size_bytes: int = Field(..., alias="fileSizeBytes", gt=0)
    duration_seconds: float = Field(..., alias="durationSeconds", gt=0)
    format: Literal["mp4", "webm"] = Field(default="mp4")


class RenderError(BaseModel):
    """Error en el renderizado"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    code: str = Field(..., description="Código de error")
    message: str = Field(..., description="Mensaje de error")
    details: Optional[str] = Field(None, description="Detalles adicionales")


class JobTimestamps(BaseModel):
    """Timestamps del trabajo"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    created: datetime = Field(..., description="Fecha de creación")
    started: Optional[datetime] = Field(None, description="Fecha de inicio")
    completed: Optional[datetime] = Field(None, description="Fecha de completación")


class RenderJobStatus(BaseModel):
    """Estado completo de un trabajo de renderizado"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    job_id: str = Field(..., alias="jobId", description="ID del trabajo")
    status: Literal["queued", "processing", "completed", "failed"] = Field(..., description="Estado")
    progress: RenderProgress = Field(..., description="Progreso actual")
    result: Optional[RenderResult] = Field(None, description="Resultado si está completado")
    error: Optional[dict] = Field(None, description="Error si falló")
    timestamps: JobTimestamps = Field(..., description="Timestamps")
    download_url: Optional[str] = Field(None, alias="downloadUrl", description="URL de descarga directa")


class JobCreatedResponse(BaseModel):
    """Response al crear un trabajo"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    job_id: str = Field(..., alias="jobId")
    status: str = "queued"
    message: str = "Trabajo de renderizado iniciado"
    status_url: str = Field(..., alias="statusUrl")


class HealthResponse(BaseModel):
    """Response del health check"""
    model_config = ConfigDict(populate_by_name=True, by_alias=True)
    
    status: str = "ok"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    ffmpeg_available: bool = False
    redis_connected: bool = False
