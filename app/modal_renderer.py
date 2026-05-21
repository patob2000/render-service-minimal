from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.modal_models import RenderRequest, SlideInput


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _guess_extension(url: str, default: str) -> str:
    try:
        path = urlparse(url).path
        suffix = Path(path).suffix
        return suffix if suffix else default
    except Exception:
        return default


def _download_to_path(client: httpx.Client, url: str, dest_path: Path, retries: int = 3) -> None:
    """
    Descarga un archivo HTTP a disco con reintentos exponenciales.

    Sin reintentos, un solo hipo del CDN (handshake TLS lento, TCP timeout,
    rate limit puntual) aborta el render entero. Con 16 slides * 2 descargas
    cada una son ~32 conexiones HTTPS por job, asi que la probabilidad
    acumulada de un fallo intermitente es alta.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    transient_errors = (
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
        httpx.PoolTimeout,
    )
    for attempt in range(1, retries + 1):
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with dest_path.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
            if attempt > 1:
                print(f"[Download] OK en intento {attempt}/{retries}: {url[:100]}")
            return
        except transient_errors as e:
            last_exc = e
            backoff = 2 ** (attempt - 1)
            print(
                f"[Download] Intento {attempt}/{retries} fallo "
                f"({type(e).__name__}: {e}). Reintentando en {backoff}s. URL={url[:100]}"
            )
            if attempt < retries:
                time.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def _prepare_slide_assets(client: httpx.Client, slide: SlideInput, job_dir: Path) -> dict[str, str]:
    import base64
    assets: dict[str, str] = {}

    # Helper para base64
    def save_base64(data: str, dest_path: Path):
        if ',' in data:
            data = data.split(',', 1)[1]
        decoded = base64.b64decode(data)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with dest_path.open('wb') as f:
            f.write(decoded)

    # Imagen de fondo
    bg_ext = _guess_extension(slide.background_image, default=".png")
    bg_path = job_dir / f"slide_{slide.index}_bg{bg_ext}"
    
    if _is_url(slide.background_image):
        _download_to_path(client, slide.background_image, bg_path)
    else:
        # Es base64
        save_base64(slide.background_image, bg_path)
    assets["background"] = str(bg_path)

    # Audio de narración
    if slide.audio_narration:
        audio_ext = _guess_extension(slide.audio_narration, default=".mp3")
        audio_path = job_dir / f"slide_{slide.index}_audio{audio_ext}"
        
        if _is_url(slide.audio_narration):
            _download_to_path(client, slide.audio_narration, audio_path)
        else:
            # Es base64
            save_base64(slide.audio_narration, audio_path)
        assets["audio"] = str(audio_path)

    # Video de avatar
    if slide.avatar_video:
        avatar_ext = _guess_extension(slide.avatar_video, default=".mp4")
        avatar_path = job_dir / f"slide_{slide.index}_avatar{avatar_ext}"
        
        if _is_url(slide.avatar_video):
            _download_to_path(client, slide.avatar_video, avatar_path)
        else:
            # Es base64
            save_base64(slide.avatar_video, avatar_path)
        assets["avatar"] = str(avatar_path)

    return assets



def render_video_to_mp4(job_id: str, request_dict: dict, jobs_dict=None) -> tuple[str, dict]:
    """
    Render a full video and return (local_mp4_path, metadata).
    This function is intended to run inside a Modal worker container.
    
    Args:
        job_id: Identificador del trabajo
        request_dict: Diccionario con la solicitud de renderizado
        jobs_dict: Modal.Dict compartido para actualizar progreso (opcional)
    """
    os.environ.setdefault("FFMPEG_THREADS", "1")

    # Import after setting env so ffmpeg_service picks up FFMPEG_THREADS safely.
    from app.models import OutputSettings, Quality, Resolution, SlideData, SlideType
    from app.services import ffmpeg_service

    req = RenderRequest.model_validate(request_dict)

    job_dir = Path("/tmp") / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_settings = OutputSettings(
        resolution=Resolution(req.resolution),
        fps=req.fps,
        quality=Quality(req.quality),
    )

    clip_paths: list[str] = []
    total_slides = len(req.slides)

    with httpx.Client(timeout=60.0) as client:
        for i, slide in enumerate(req.slides, start=1):
            # Actualizar progreso antes de procesar este slide
            if jobs_dict is not None:
                progress_percent = int((i - 1) / total_slides * 100)
                jobs_dict[job_id] = {
                    "status": "processing",
                    "message": f"Procesando diapositiva {i}/{total_slides}",
                    "current_slide": i,
                    "total_slides": total_slides,
                    "progress": progress_percent,
                    "updated_at": time.time(),
                }
            
            assets = _prepare_slide_assets(client, slide, job_dir)

            clip_path = str(job_dir / f"clip_{slide.index}.mp4")

            slide_data = SlideData(
                index=slide.index,
                type=SlideType.CONTENIDO,
                titulo=slide.titulo,
                backgroundImage=slide.background_image,
                duration=slide.duration,
            )

            ffmpeg_service.render_slide(
                slide=slide_data,
                background_path=assets["background"],
                output_path=clip_path,
                settings=output_settings,
                avatar_path=assets.get("avatar"),
                audio_path=assets.get("audio"),
            )

            clip_paths.append(clip_path)

    # Actualizar progreso antes de concatenar
    if jobs_dict is not None:
        jobs_dict[job_id] = {
            "status": "processing",
            "message": f"Concatenando {total_slides} clips...",
            "current_slide": total_slides,
            "total_slides": total_slides,
            "progress": 90,
            "updated_at": time.time(),
        }

    output_mp4_path = str(job_dir / "output.mp4")
    ffmpeg_service.concatenate_clips(clip_paths, output_mp4_path, output_settings)

    file_size_bytes = os.path.getsize(output_mp4_path)
    duration_seconds = ffmpeg_service.get_media_duration(output_mp4_path)

    return output_mp4_path, {
        "file_size_bytes": file_size_bytes,
        "duration_seconds": duration_seconds,
        "slides": len(req.slides),
    }

