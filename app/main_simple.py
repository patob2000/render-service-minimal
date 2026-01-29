"""
FastAPI Simple - Video Render Service (Sin Celery/Redis)
Versión optimizada para Easypanel con 2GB RAM
"""
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field
import uuid
import os
import tempfile
import shutil
import base64
import httpx
import asyncio
import traceback
import time
import concurrent.futures
from functools import partial

from app.config import get_settings, RESOLUTIONS, QUALITY_CRF
from app.services import ffmpeg_service

settings = get_settings()

# ThreadPoolExecutor global para evitar recrearlo en cada job
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Obtiene el ThreadPoolExecutor global"""
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    return _executor

# Caché para health check de FFmpeg
_ffmpeg_check_cache = {"result": None, "timestamp": 0}
FFMPEG_CHECK_CACHE_TTL = 60  # segundos

def check_ffmpeg_cached() -> bool:
    """Verifica FFmpeg con caché de 60 segundos"""
    now = time.time()
    if _ffmpeg_check_cache["result"] is None or (now - _ffmpeg_check_cache["timestamp"]) > FFMPEG_CHECK_CACHE_TTL:
        _ffmpeg_check_cache["result"] = ffmpeg_service.check_ffmpeg()
        _ffmpeg_check_cache["timestamp"] = now
    return _ffmpeg_check_cache["result"]


class CORSErrorMiddleware(BaseHTTPMiddleware):
    """Middleware para asegurar que los errores también tengan headers CORS"""
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            print(f"❌ Error no manejado: {str(e)}")
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"detail": str(e)},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                }
            )


# =============================================================================
# Modelos simplificados
# =============================================================================

class SlideInput(BaseModel):
    """Datos de una diapositiva"""
    index: int
    titulo: str = ""
    background_image: str = Field(..., alias="backgroundImage")  # URL o base64
    audio_narration: Optional[str] = Field(None, alias="audioNarration")  # base64
    avatar_video: Optional[str] = Field(None, alias="avatarVideo")  # URL
    duration: Optional[float] = None

    class Config:
        populate_by_name = True


class RenderRequest(BaseModel):
    """Request para renderizar video"""
    project_name: str = Field(..., alias="projectName")
    slides: list[SlideInput]
    resolution: str = "1080p"
    fps: int = 30
    quality: str = "high"

    class Config:
        populate_by_name = True


# =============================================================================
# Almacenamiento en memoria de trabajos
# =============================================================================

jobs_store: dict[str, dict] = {}


# =============================================================================
# Aplicación FastAPI
# =============================================================================

async def cleanup_old_files():
    """Limpia archivos temporales huérfanos de más de 1 hora"""
    max_age_seconds = 3600  # 1 hora
    now = time.time()
    cleaned_count = 0
    
    for directory in [settings.temp_dir, settings.output_dir]:
        if not os.path.exists(directory):
            continue
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            try:
                # Obtener tiempo de modificación
                mtime = os.path.getmtime(item_path)
                if now - mtime > max_age_seconds:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        os.remove(item_path)
                    cleaned_count += 1
            except Exception as e:
                print(f"⚠️ Error limpiando {item_path}: {e}")
    
    if cleaned_count > 0:
        print(f"🧹 Limpiados {cleaned_count} archivos/directorios antiguos")


async def periodic_cleanup():
    """Tarea periódica de limpieza cada 30 minutos"""
    while True:
        await asyncio.sleep(1800)  # 30 minutos
        await cleanup_old_files()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle hooks"""
    global _executor
    
    # Crear directorios
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    
    # Limpieza inicial de archivos huérfanos
    await cleanup_old_files()
    
    # Iniciar tarea periódica de limpieza
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    print(f"✅ Video Render API iniciado en puerto {settings.api_port}")
    print(f"✅ FFmpeg disponible: {check_ffmpeg_cached()}")
    print(f"✅ Limpieza automática activa (cada 30 min)")
    
    yield
    
    # Cleanup al cerrar
    cleanup_task.cancel()
    if _executor:
        _executor.shutdown(wait=False)
    print("👋 Cerrando Video Render API")


app = FastAPI(
    title="EduSlide Video Render API",
    description="API simple para renderizar videos MP4",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)

# Agregar middleware de errores CORS primero (se ejecuta último)
app.add_middleware(CORSErrorMiddleware)

# CORS - permitir todos los orígenes para desarrollo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Cambiado a False para permitir "*" en origins
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Endpoint OPTIONS manual para preflight
@app.options("/{full_path:path}")
async def preflight_handler(request: Request, full_path: str):
    """Maneja preflight CORS requests"""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        }
    )


# =============================================================================
# Utilidades
# =============================================================================

async def download_file(url: str, dest_path: str) -> str:
    """Descarga un archivo desde URL"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(response.content)
    return dest_path


def save_base64_file(data: str, dest_path: str) -> str:
    """Guarda datos base64 a archivo"""
    # Remover prefijo data URI si existe
    if ',' in data:
        data = data.split(',', 1)[1]
    
    decoded = base64.b64decode(data)
    with open(dest_path, 'wb') as f:
        f.write(decoded)
    return dest_path


def is_url(s: str) -> bool:
    """Verifica si es una URL"""
    return s.startswith('http://') or s.startswith('https://')


def is_base64(s: str) -> bool:
    """Verifica si parece ser base64"""
    return len(s) > 100 and not is_url(s)


async def prepare_slide_assets(
    slide: SlideInput, 
    job_dir: str, 
    slide_index: int
) -> dict:
    """Prepara los assets de una diapositiva descargando/decodificando archivos"""
    assets = {}
    
    # Imagen de fondo
    bg_path = os.path.join(job_dir, f"slide_{slide_index}_bg.png")
    if is_url(slide.background_image):
        await download_file(slide.background_image, bg_path)
    else:
        save_base64_file(slide.background_image, bg_path)
    assets['background'] = bg_path
    
    # Audio de narración
    if slide.audio_narration:
        audio_path = os.path.join(job_dir, f"slide_{slide_index}_audio.mp3")
        if is_url(slide.audio_narration):
            await download_file(slide.audio_narration, audio_path)
        else:
            save_base64_file(slide.audio_narration, audio_path)
        assets['audio'] = audio_path
    
    # Video de avatar
    if slide.avatar_video:
        avatar_path = os.path.join(job_dir, f"slide_{slide_index}_avatar.mp4")
        if is_url(slide.avatar_video):
            await download_file(slide.avatar_video, avatar_path)
        else:
            save_base64_file(slide.avatar_video, avatar_path)
        assets['avatar'] = avatar_path
    
    return assets


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check (FFmpeg cacheado por 60s)"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "ffmpeg_available": check_ffmpeg_cached(),
        "version": "2.1.0"
    }


@app.post("/api/render")
async def render_video_sync(request: RenderRequest):
    """
    Renderiza un video de forma SÍNCRONA.
    Espera hasta que el video esté listo y lo devuelve.
    
    ⚠️ Para videos largos, usar /api/render/async en su lugar.
    """
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(settings.temp_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    try:
        clip_paths = []
        
        # Crear OutputSettings para ffmpeg_service
        from app.models import OutputSettings, Resolution, Quality
        output_settings = OutputSettings(
            resolution=Resolution(request.resolution),
            fps=request.fps,
            quality=Quality(request.quality)
        )
        
        # Procesar cada diapositiva
        for i, slide in enumerate(request.slides):
            print(f"[Job {job_id}] Procesando slide {i + 1}/{len(request.slides)}")
            
            # Preparar assets
            assets = await prepare_slide_assets(slide, job_dir, i)
            
            # Renderizar slide
            clip_path = os.path.join(job_dir, f"clip_{i}.mp4")
            
            # Crear objeto SlideData minimal
            from app.models import SlideData, SlideType
            slide_data = SlideData(
                index=i,
                type=SlideType.CONTENIDO,
                titulo=slide.titulo,
                backgroundImage=slide.background_image,
                duration=slide.duration
            )
            
            ffmpeg_service.render_slide(
                slide=slide_data,
                background_path=assets['background'],
                output_path=clip_path,
                settings=output_settings,
                avatar_path=assets.get('avatar'),
                audio_path=assets.get('audio')
            )
            
            clip_paths.append(clip_path)
        
        # Concatenar todos los clips
        output_path = os.path.join(settings.output_dir, f"{job_id}.mp4")
        ffmpeg_service.concatenate_clips(clip_paths, output_path, output_settings)
        
        # Obtener tamaño del archivo
        file_size = os.path.getsize(output_path)
        duration = ffmpeg_service.get_media_duration(output_path)
        
        print(f"[Job {job_id}] ✅ Video completado: {output_path}")
        
        # Guardar info del job
        jobs_store[job_id] = {
            "status": "completed",
            "output_path": output_path,
            "file_size": file_size,
            "duration": duration,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Limpiar temp después de un delay
        asyncio.create_task(cleanup_after_delay(job_dir, 60))
        
        return {
            "jobId": job_id,
            "status": "completed",
            "downloadUrl": f"/api/render/{job_id}/download",
            "fileSizeBytes": file_size,
            "durationSeconds": duration
        }
        
    except Exception as e:
        # Limpiar en caso de error
        shutil.rmtree(job_dir, ignore_errors=True)
        print(f"[Job {job_id}] ❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/render/async")
async def render_video_async(request: RenderRequest, background_tasks: BackgroundTasks):
    """
    Inicia un renderizado ASÍNCRONO.
    Devuelve inmediatamente un job_id para consultar el estado.
    """
    job_id = str(uuid.uuid4())
    
    # Inicializar estado
    jobs_store[job_id] = {
        "status": "processing",
        "progress": 0,
        "message": "Iniciando...",
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Ejecutar en background
    background_tasks.add_task(process_render_job, job_id, request)
    
    return {
        "jobId": job_id,
        "status": "processing",
        "statusUrl": f"/api/render/{job_id}/status"
    }


def render_slide_sync(slide_data, background_path, clip_path, output_settings, avatar_path, audio_path):
    """Wrapper sincrónico para render_slide"""
    import gc
    result = ffmpeg_service.render_slide(
        slide=slide_data,
        background_path=background_path,
        output_path=clip_path,
        settings=output_settings,
        avatar_path=avatar_path,
        audio_path=audio_path
    )
    gc.collect()  # Forzar garbage collection
    return result


def concatenate_sync(clip_paths, output_path, output_settings):
    """Wrapper sincrónico para concatenate_clips"""
    import gc
    result = ffmpeg_service.concatenate_clips(clip_paths, output_path, output_settings)
    gc.collect()
    return result


async def process_render_job(job_id: str, request: RenderRequest):
    """
    Procesa un trabajo de renderizado en background.
    Optimizado con:
    - ThreadPoolExecutor global (no se recrea por job)
    - Pre-descarga de assets del siguiente slide mientras renderiza el actual
    """
    import gc
    
    job_dir = os.path.join(settings.temp_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    print(f"[Job {job_id}] Iniciando procesamiento de {len(request.slides)} slides")
    
    loop = asyncio.get_running_loop()
    executor = get_executor()  # Usar executor global
    
    try:
        clip_paths = []
        total_slides = len(request.slides)
        
        from app.models import OutputSettings, Resolution, Quality, SlideData, SlideType
        
        output_settings = OutputSettings(
            resolution=Resolution(request.resolution),
            fps=request.fps,
            quality=Quality(request.quality)
        )
        print(f"[Job {job_id}] Configuración: {request.resolution}, {request.fps}fps, calidad {request.quality}")
        
        # Pre-descargar assets del primer slide
        next_assets_task = asyncio.create_task(
            prepare_slide_assets(request.slides[0], job_dir, 0)
        )
        
        for i, slide in enumerate(request.slides):
            print(f"[Job {job_id}] Procesando slide {i + 1}/{total_slides}")
            
            # Actualizar progreso
            progress = int((i / total_slides) * 80)
            jobs_store[job_id].update({
                "progress": progress,
                "message": f"Procesando diapositiva {i + 1}/{total_slides}",
                "current_slide": i + 1,
                "total_slides": total_slides
            })
            
            # Esperar assets del slide actual (ya pre-descargados)
            assets = await next_assets_task
            clip_path = os.path.join(job_dir, f"clip_{i}.mp4")
            
            # Iniciar pre-descarga del siguiente slide mientras renderizamos
            if i + 1 < total_slides:
                next_assets_task = asyncio.create_task(
                    prepare_slide_assets(request.slides[i + 1], job_dir, i + 1)
                )
            
            slide_data = SlideData(
                index=i,
                type=SlideType.CONTENIDO,
                titulo=slide.titulo,
                backgroundImage=slide.background_image,
                duration=slide.duration
            )
            
            # Ejecutar FFmpeg en thread pool
            render_func = partial(
                render_slide_sync,
                slide_data,
                assets['background'],
                clip_path,
                output_settings,
                assets.get('avatar'),
                assets.get('audio')
            )
            
            await loop.run_in_executor(executor, render_func)
            
            clip_paths.append(clip_path)
            print(f"[Job {job_id}] Slide {i + 1} completado")
            
            # Pequeña pausa para permitir que el event loop procese otras requests
            await asyncio.sleep(0.05)
        
        # Concatenar
        print(f"[Job {job_id}] Concatenando {len(clip_paths)} clips")
        jobs_store[job_id].update({
            "progress": 85,
            "message": "Concatenando videos..."
        })
        
        output_path = os.path.join(settings.output_dir, f"{job_id}.mp4")
        
        concat_func = partial(concatenate_sync, clip_paths, output_path, output_settings)
        await loop.run_in_executor(executor, concat_func)
        
        file_size = os.path.getsize(output_path)
        duration = ffmpeg_service.get_media_duration(output_path)
        
        print(f"[Job {job_id}] ✅ Completado: {file_size} bytes, {duration}s")
        
        # Completado
        jobs_store[job_id].update({
            "status": "completed",
            "progress": 100,
            "message": "Video completado",
            "output_path": output_path,
            "file_size": file_size,
            "duration": duration,
            "download_url": f"/api/render/{job_id}/download",
            "completed_at": datetime.utcnow().isoformat()
        })
        
        # Limpiar temp
        shutil.rmtree(job_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"[Job {job_id}] ❌ Error: {str(e)}")
        traceback.print_exc()
        jobs_store[job_id].update({
            "status": "failed",
            "progress": 0,
            "message": str(e),
            "error": str(e)
        })
        shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/api/render/{job_id}/status")
async def get_job_status(job_id: str):
    """Obtiene el estado de un trabajo"""
    if job_id not in jobs_store:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    
    job = jobs_store[job_id]
    return {
        "jobId": job_id,
        "status": job.get("status", "unknown"),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "currentSlide": job.get("current_slide"),
        "totalSlides": job.get("total_slides"),
        "downloadUrl": job.get("download_url"),
        "fileSizeBytes": job.get("file_size"),
        "durationSeconds": job.get("duration"),
        "error": job.get("error")
    }


@app.get("/api/render/{job_id}/download")
async def download_video(job_id: str):
    """Descarga el video renderizado"""
    if job_id not in jobs_store:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    
    job = jobs_store[job_id]
    
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Video aún no está listo")
    
    output_path = job.get("output_path")
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    return FileResponse(
        path=output_path,
        filename=f"video_{job_id}.mp4",
        media_type="video/mp4"
    )


@app.delete("/api/render/{job_id}")
async def delete_job(job_id: str, background_tasks: BackgroundTasks):
    """Elimina un trabajo y sus archivos"""
    if job_id in jobs_store:
        job = jobs_store[job_id]
        output_path = job.get("output_path")
        if output_path and os.path.exists(output_path):
            background_tasks.add_task(os.remove, output_path)
        del jobs_store[job_id]
    
    return {"message": "Job eliminado", "jobId": job_id}


async def cleanup_after_delay(path: str, delay_seconds: int):
    """Limpia un directorio después de un delay"""
    await asyncio.sleep(delay_seconds)
    shutil.rmtree(path, ignore_errors=True)


# =============================================================================
# Punto de entrada
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main_simple:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
