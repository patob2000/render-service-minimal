from __future__ import annotations

import os
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


def _download_to_path(client: httpx.Client, url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)


def _prepare_slide_assets(client: httpx.Client, slide: SlideInput, job_dir: Path) -> dict[str, str]:
    assets: dict[str, str] = {}

    bg_ext = _guess_extension(slide.background_image, default=".png")
    bg_path = job_dir / f"slide_{slide.index}_bg{bg_ext}"
    if _is_url(slide.background_image):
        _download_to_path(client, slide.background_image, bg_path)
    else:
        raise ValueError("backgroundImage must be a URL in the Modal render worker")
    assets["background"] = str(bg_path)

    if slide.audio_narration:
        audio_ext = _guess_extension(slide.audio_narration, default=".mp3")
        audio_path = job_dir / f"slide_{slide.index}_audio{audio_ext}"
        if _is_url(slide.audio_narration):
            _download_to_path(client, slide.audio_narration, audio_path)
        else:
            raise ValueError("audioNarration must be a URL in the Modal render worker")
        assets["audio"] = str(audio_path)

    if slide.avatar_video:
        avatar_ext = _guess_extension(slide.avatar_video, default=".mp4")
        avatar_path = job_dir / f"slide_{slide.index}_avatar{avatar_ext}"
        if _is_url(slide.avatar_video):
            _download_to_path(client, slide.avatar_video, avatar_path)
        else:
            raise ValueError("avatarVideo must be a URL in the Modal render worker")
        assets["avatar"] = str(avatar_path)

    return assets


def render_video_to_mp4(job_id: str, request_dict: dict) -> tuple[str, dict]:
    """
    Render a full video and return (local_mp4_path, metadata).
    This function is intended to run inside a Modal worker container.
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

    with httpx.Client(timeout=60.0) as client:
        for slide in req.slides:
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

    output_mp4_path = str(job_dir / "output.mp4")
    ffmpeg_service.concatenate_clips(clip_paths, output_mp4_path, output_settings)

    file_size_bytes = os.path.getsize(output_mp4_path)
    duration_seconds = ffmpeg_service.get_media_duration(output_mp4_path)

    return output_mp4_path, {
        "file_size_bytes": file_size_bytes,
        "duration_seconds": duration_seconds,
        "slides": len(req.slides),
    }

