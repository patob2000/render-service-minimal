"""
Servicio de renderizado de video con FFmpeg
Optimizado para servidor con múltiples CPUs y alta RAM
"""
import ffmpeg
import os
import subprocess
from pathlib import Path
from typing import Optional

from app.config import get_settings, RESOLUTIONS, QUALITY_CRF
from app.models import SlideData, OutputSettings

settings = get_settings()

# Detectar número de CPUs disponibles
CPU_COUNT = os.cpu_count() or 4

# Configuración de threads para FFmpeg.
# - Si FFMPEG_THREADS no está definido: se mantiene el comportamiento actual (0 = auto-detect).
# - En Modal recomendamos FFMPEG_THREADS=1 (o 2 si asignas >=4 CPU) para evitar oversubscription.
def _parse_ffmpeg_threads() -> int:
    raw = os.environ.get("FFMPEG_THREADS")
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except ValueError:
        log_warning("Invalid FFMPEG_THREADS env var, falling back to auto", raw=raw)
        return 0
    if value < 0:
        log_warning("Negative FFMPEG_THREADS is invalid, falling back to auto", raw=raw)
        return 0
    return value


FFMPEG_THREADS = _parse_ffmpeg_threads()


def log_info(msg: str, **kwargs):
    print(f"[FFmpeg] {msg}", kwargs if kwargs else "")


def log_warning(msg: str, **kwargs):
    print(f"[FFmpeg WARN] {msg}", kwargs if kwargs else "")


def log_error(msg: str, **kwargs):
    print(f"[FFmpeg ERROR] {msg}", kwargs if kwargs else "")


def check_ffmpeg() -> bool:
    """Verifica que FFmpeg esté disponible"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_media_duration(file_path: str) -> float:
    """Obtiene la duración de un archivo multimedia"""
    try:
        probe = ffmpeg.probe(file_path)
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        log_warning("Could not get media duration", file=file_path, error=str(e))
        return 5.0  # Default 5 segundos


def render_slide_with_avatar(
    background_path: str,
    avatar_video_path: str,
    output_path: str,
    settings: OutputSettings,
    duration: Optional[float] = None
) -> str:
    """
    Renderiza una diapositiva con imagen de fondo y video de avatar superpuesto.
    
    Esta es la versión elegante con ffmpeg-python vs el código verboso de Node.js
    """
    width, height = RESOLUTIONS[settings.resolution.value]
    crf = QUALITY_CRF[settings.quality.value]
    
    # Obtener duración del video de avatar
    if duration is None:
        duration = get_media_duration(avatar_video_path)
    
    log_info("Rendering slide with avatar",
             background=background_path,
             avatar=avatar_video_path,
             duration=duration)
    
    # Input streams
    background = ffmpeg.input(background_path, loop=1, t=duration)
    avatar = ffmpeg.input(avatar_video_path)
    
    # Padding más grande para achicar la imagen (proporcional al frontend)
    # Frontend tiene p-6 pr-16 pb-8 en ~900px, pero se ve más pequeña
    pad_top = 48
    pad_right = 120
    pad_bottom = 80
    pad_left = 48
    corner_radius = 24  # Bordes redondeados
    
    # Tamaño de la imagen con padding
    img_w = width - pad_left - pad_right
    img_h = height - pad_top - pad_bottom
    
    # Crear fondo gris (gradiente simulado con color sólido)
    gray_bg = ffmpeg.input(f'color=#f1f5f9:s={width}x{height}:d={duration}', f='lavfi')
    
    # Procesar imagen: escalar para llenar el área (cover) - sin bordes negros
    bg_scaled = (
        background
        .filter('scale', img_w, img_h, force_original_aspect_ratio='increase')
        .filter('crop', img_w, img_h)  # Recortar excedente en lugar de agregar padding
        .filter('setsar', 1)
    )
    
    # Aplicar bordes redondeados a la imagen usando máscara
    # Crear máscara con esquinas redondeadas
    r = corner_radius
    bg_rounded = (
        bg_scaled
        .filter('format', 'rgba')
        .filter('geq',
                r='r(X,Y)',
                g='g(X,Y)',
                b='b(X,Y)',
                a=f'if(lt(X,{r})*lt(Y,{r}),if(lt(hypot({r}-X,{r}-Y),{r}),255,0),'
                  f'if(gt(X,{img_w}-{r})*lt(Y,{r}),if(lt(hypot(X-{img_w}+{r},{r}-Y),{r}),255,0),'
                  f'if(lt(X,{r})*gt(Y,{img_h}-{r}),if(lt(hypot({r}-X,Y-{img_h}+{r}),{r}),255,0),'
                  f'if(gt(X,{img_w}-{r})*gt(Y,{img_h}-{r}),if(lt(hypot(X-{img_w}+{r},Y-{img_h}+{r}),{r}),255,0),'
                  f'255))))')
    )
    
    # Superponer imagen sobre fondo gris (centrada con offset del padding)
    # La imagen va alineada abajo (items-end en frontend)
    img_y = height - img_h - pad_bottom
    bg_with_padding = ffmpeg.overlay(gray_bg, bg_rounded, x=pad_left, y=img_y)
    
    # Procesar avatar: circular mask con borde blanco suave
    # Proporcional al diseño frontend: w-48 (192px) en ~900px viewport = ~21% del ancho
    # Para 1920px: ~400px de avatar
    avatar_size = 384  # Tamaño del avatar circular
    border_width = 6   # Grosor del borde blanco (proporcional)
    total_size = avatar_size + (border_width * 2)  # Tamaño total incluyendo borde
    feather = 3  # Suavizado del borde (antialiasing)
    
    # Escalar el avatar al tamaño deseado con alta calidad
    avatar_scaled = (
        avatar
        .filter('scale', avatar_size, avatar_size, flags='lanczos')
    )
    
    # Crear el avatar circular con máscara suave (antialiasing)
    # Usamos formato rgba para preservar colores, y clip para suavizar el borde
    r_avatar = avatar_size // 2
    avatar_circular = (
        avatar_scaled
        .filter('format', 'rgba')
        .filter('geq',
                r='r(X,Y)',
                g='g(X,Y)',
                b='b(X,Y)',
                a=f'clip(({r_avatar}-sqrt(pow(X-{r_avatar},2)+pow(Y-{r_avatar},2)))/{feather}*255,0,255)')
    )
    
    # Crear un círculo blanco como borde con antialiasing
    r_total = total_size // 2
    white_circle = (
        ffmpeg.input(f'color=white:s={total_size}x{total_size}:d={duration}', f='lavfi')
        .filter('format', 'rgba')
        .filter('geq',
                r='255',
                g='255',
                b='255',
                a=f'clip(({r_total}-sqrt(pow(X-{r_total},2)+pow(Y-{r_total},2)))/{feather}*255,0,255)')
    )
    
    # Superponer el avatar sobre el borde blanco
    avatar_processed = (
        ffmpeg.overlay(white_circle, avatar_circular, x=border_width, y=border_width)
    )
    
    # Posición del avatar (esquina inferior derecha - diseño circular)
    # En frontend: bottom-6 right-6 (~24px en ~540px alto) = ~4.4% del alto
    # Para 1080px: ~48px de margen
    overlay_x = width - total_size - 48
    overlay_y = height - total_size - 48
    
    # Composición final - con 2GB RAM podemos usar mejor calidad.
    # Forzamos parametros homogeneos entre tipos de clip (CFR, GOP fijo, audio uniforme)
    # para que el concat final no tenga saltos de timestamps que rompen la sincronizacion.
    output = (
        ffmpeg
        .overlay(bg_with_padding, avatar_processed, x=overlay_x, y=overlay_y, shortest=1)
        .output(
            ffmpeg.input(avatar_video_path).audio,  # Audio del avatar
            output_path,
            vcodec='libx264',
            acodec='aac',
            audio_bitrate='192k',
            preset='veryfast',
            crf=crf,
            r=settings.fps,
            pix_fmt='yuv420p',
            ar=44100,
            ac=2,
            vsync='cfr',
            g=settings.fps * 2,
            movflags='+faststart',
            t=duration,
            threads=FFMPEG_THREADS,
            **{'video_track_timescale': 90000},
        )
        .overwrite_output()
    )
    
    # Ejecutar
    try:
        output.run(capture_stdout=True, capture_stderr=True)
        log_info("Slide rendered successfully", output=output_path)
        return output_path
    except ffmpeg.Error as e:
        log_error("FFmpeg error", stderr=e.stderr.decode() if e.stderr else None)
        raise


def render_slide_with_audio(
    background_path: str,
    audio_path: str,
    output_path: str,
    settings: OutputSettings,
) -> str:
    """
    Renderiza una diapositiva con imagen de fondo y audio (sin avatar)
    """
    width, height = RESOLUTIONS[settings.resolution.value]
    crf = QUALITY_CRF[settings.quality.value]
    
    duration = get_media_duration(audio_path)
    
    log_info("Rendering slide with audio",
             background=background_path,
             audio=audio_path,
             duration=duration)
    
    # Imagen de fondo en loop + audio. Sin tune='stillimage' (deja GOP enorme y
    # frames no uniformes, lo que rompe el concat reencode). Forzamos CFR + GOP fijo
    # + audio uniforme para que sea identico estructuralmente a render_slide_with_avatar.
    output = (
        ffmpeg
        .input(background_path, loop=1, t=duration, framerate=settings.fps)
        .filter('scale', width, height, force_original_aspect_ratio='decrease')
        .filter('pad', width, height, '(ow-iw)/2', '(oh-ih)/2')
        .filter('fps', fps=settings.fps)
        .output(
            ffmpeg.input(audio_path),
            output_path,
            vcodec='libx264',
            acodec='aac',
            audio_bitrate='192k',
            preset='veryfast',
            crf=crf,
            r=settings.fps,
            pix_fmt='yuv420p',
            ar=44100,
            ac=2,
            vsync='cfr',
            g=settings.fps * 2,
            movflags='+faststart',
            t=duration,
            threads=FFMPEG_THREADS,
            **{'video_track_timescale': 90000},
        )
        .overwrite_output()
    )
    
    try:
        output.run(capture_stdout=True, capture_stderr=True)
        log_info("Slide rendered successfully", output=output_path)
        return output_path
    except ffmpeg.Error as e:
        log_error("FFmpeg error", stderr=e.stderr.decode() if e.stderr else None)
        raise


def render_slide_static(
    background_path: str,
    output_path: str,
    settings: OutputSettings,
    duration: float = 5.0
) -> str:
    """
    Renderiza una diapositiva estática (solo imagen, sin audio)
    Agrega audio silencioso para permitir concatenación
    """
    width, height = RESOLUTIONS[settings.resolution.value]
    crf = QUALITY_CRF[settings.quality.value]
    
    log_info("Rendering static slide",
             background=background_path,
             duration=duration)
    
    # Imagen + audio silencioso
    video = (
        ffmpeg
        .input(background_path, loop=1, t=duration)
        .filter('scale', width, height, force_original_aspect_ratio='decrease')
        .filter('pad', width, height, '(ow-iw)/2', '(oh-ih)/2')
    )
    
    audio = ffmpeg.input('anullsrc=r=44100:cl=stereo', f='lavfi', t=duration)
    
    output = (
        ffmpeg
        .output(video, audio, output_path,
                vcodec='libx264',
                acodec='aac',
                audio_bitrate='64k',
                tune='stillimage',
                preset='veryfast',  # Máxima velocidad
                crf=crf,
                r=settings.fps,
                pix_fmt='yuv420p',
                movflags='+faststart',
                threads=FFMPEG_THREADS)
        .overwrite_output()
    )
    
    try:
        output.run(capture_stdout=True, capture_stderr=True)
        log_info("Static slide rendered", output=output_path)
        return output_path
    except ffmpeg.Error as e:
        log_error("FFmpeg error", stderr=e.stderr.decode() if e.stderr else None)
        raise


def concatenate_clips(
    clip_paths: list[str],
    output_path: str,
    settings: OutputSettings
) -> str:
    """
    Concatena múltiples clips en un video final
    """
    crf = QUALITY_CRF[settings.quality.value]
    
    log_info("Concatenating clips", count=len(clip_paths))
    
    # Crear archivo de lista para concat
    list_path = output_path.replace('.mp4', '_concat_list.txt')
    with open(list_path, 'w') as f:
        for clip in clip_paths:
            # Usar rutas absolutas para evitar problemas de resolución relativa
            absolute_clip = str(Path(clip).resolve())
            # Escapar comillas simples en paths
            escaped_path = absolute_clip.replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")
    
    try:
        # Concat demuxer con RE-ENCODE completo (video + audio). Razón:
        # los clips de avatar (vienen de Wavespeed reprocesados) y los clips imagen+audio
        # quedan con metadatos sutilmente distintos (timebase, sample rate, SAR, fps efectivo).
        # Con vcodec=copy/acodec=copy el reproductor cambia de formato a mitad y se escucha
        # ruido / video congela en las transiciones. Reencodear todo garantiza un MP4 uniforme.
        # Coste: ~10-20% mas tiempo, pero salida correcta.
        crf_str = str(crf)
        output = (
            ffmpeg
            .input(list_path, f='concat', safe=0)
            .output(output_path,
                    vcodec='libx264',
                    preset='veryfast',
                    crf=crf_str,
                    pix_fmt='yuv420p',
                    r=settings.fps,
                    acodec='aac',
                    audio_bitrate='192k',
                    ar=44100,
                    ac=2,
                    movflags='+faststart')
            .overwrite_output()
        )
        
        output.run(capture_stdout=True, capture_stderr=True)
        log_info("Concatenation completed", output=output_path)
        
        return output_path
        
    except ffmpeg.Error as e:
        log_error("Concat error", stderr=e.stderr.decode() if e.stderr else None)
        raise
    finally:
        # Limpiar archivo de lista
        if os.path.exists(list_path):
            os.remove(list_path)


def render_slide(
    slide: SlideData,
    background_path: str,
    output_path: str,
    settings: OutputSettings,
    avatar_path: Optional[str] = None,
    audio_path: Optional[str] = None
) -> str:
    """
    Renderiza una diapositiva según los recursos disponibles
    """
    if avatar_path and os.path.exists(avatar_path):
        # Con avatar (video overlay)
        return render_slide_with_avatar(
            background_path=background_path,
            avatar_video_path=avatar_path,
            output_path=output_path,
            settings=settings,
            duration=slide.duration
        )
    elif audio_path and os.path.exists(audio_path):
        # Solo audio
        return render_slide_with_audio(
            background_path=background_path,
            audio_path=audio_path,
            output_path=output_path,
            settings=settings
        )
    else:
        # Solo imagen
        return render_slide_static(
            background_path=background_path,
            output_path=output_path,
            settings=settings,
            duration=slide.duration or 5.0
        )
