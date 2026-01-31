from __future__ import annotations

import time
import uuid

import modal
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from modal_models import RenderRequest
from renderer import render_video_to_mp4
from storage import presign_download_url, upload_mp4


MODAL_APP_NAME = "render-service"
S3_SECRET_NAME = "render-s3"
JOBS_DICT_NAME = "render-jobs"

S3_OUTPUT_PREFIX = "renders/"
PRESIGN_EXPIRES_SECONDS = 24 * 60 * 60

app = modal.App(MODAL_APP_NAME)

jobs = modal.Dict.from_name(JOBS_DICT_NAME, create_if_missing=True)
s3_secret = modal.Secret.from_name(S3_SECRET_NAME)


image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install(
        "fastapi==0.109.0",
        "pydantic==2.5.3",
        "httpx==0.26.0",
        "boto3==1.34.0",
        "ffmpeg-python==0.2.0",
    )
)


@app.function(
    image=image,
    secrets=[s3_secret],
    include_source=True,
    cpu=2,
    memory=4096,
    timeout=3600,
    max_containers=4,
    allow_concurrent_inputs=1,
)
def render_worker(job_id: str, request_dict: dict) -> None:
    jobs[job_id] = {
        "status": "processing",
        "message": "Rendering",
        "updated_at": time.time(),
    }

    try:
        local_mp4_path, meta = render_video_to_mp4(job_id, request_dict)

        s3_key = f"{S3_OUTPUT_PREFIX}{job_id}.mp4"
        upload_mp4(local_mp4_path, s3_key)
        output_url = presign_download_url(s3_key, expires_seconds=PRESIGN_EXPIRES_SECONDS)

        jobs[job_id] = {
            "status": "completed",
            "message": "Done",
            "updated_at": time.time(),
            "s3_key": s3_key,
            "output_url": output_url,
            "meta": meta,
        }
    except Exception as e:
        jobs[job_id] = {
            "status": "failed",
            "message": "Failed",
            "updated_at": time.time(),
            "error": str(e),
        }
        raise


web_app = FastAPI(title="EduSlide Video Render API (Modal)", version="0.1.0")


@web_app.post("/api/render/async")
async def render_async(request: RenderRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "updated_at": time.time()}

    call = render_worker.spawn(job_id, request.model_dump(by_alias=True))

    # Store call id for debugging/traceability (best-effort, SDK-dependent).
    jobs[job_id] = {
        "status": "queued",
        "updated_at": time.time(),
        "call_id": getattr(call, "object_id", None) or getattr(call, "call_id", None) or str(call),
    }

    return {
        "jobId": job_id,
        "status": "processing",
        "statusUrl": f"/api/render/{job_id}/status",
    }


@web_app.get("/api/render/{job_id}/status")
async def render_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "jobId": job_id,
        "status": job.get("status", "unknown"),
        "message": job.get("message", ""),
        "error": job.get("error"),
        "outputUrl": job.get("output_url"),
        "downloadUrl": f"/api/render/{job_id}/download",
        "meta": job.get("meta"),
    }


@web_app.get("/api/render/{job_id}/download")
async def render_download(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Video is not ready")

    output_url = job.get("output_url")
    if not output_url:
        raise HTTPException(status_code=500, detail="Missing output URL")

    return RedirectResponse(url=output_url, status_code=302)

@app.function(image=image, include_source=True)
@modal.asgi_app()
def fastapi_app():
    return web_app

