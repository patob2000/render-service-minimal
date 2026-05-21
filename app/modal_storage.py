from __future__ import annotations

import os

import boto3


def _get_bucket_and_region() -> tuple[str, str]:
    bucket = os.environ.get("AWS_S3_BUCKET")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not bucket:
        raise RuntimeError("Missing AWS_S3_BUCKET in environment")
    if not region:
        raise RuntimeError("Missing AWS_REGION (or AWS_DEFAULT_REGION) in environment")
    return bucket, region


def _s3_client():
    # Credentials are injected via Modal Secret (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY).
    return boto3.client("s3", region_name=_get_bucket_and_region()[1])


def upload_mp4(local_path: str, key: str) -> None:
    bucket, _ = _get_bucket_and_region()
    client = _s3_client()
    client.upload_file(
        Filename=local_path,
        Bucket=bucket,
        Key=key,
        ExtraArgs={"ContentType": "video/mp4"},
    )


def presign_download_url(key: str, expires_seconds: int = 86400) -> str:
    """
    Genera una URL presignada para descargar el MP4 desde S3.
    Incluye ResponseContentDisposition para forzar descarga (attachment)
    en lugar de reproduccion inline en el navegador. Sin esto, Chrome ignora
    el atributo download del <a> cuando es cross-origin y abre el video.
    """
    bucket, _ = _get_bucket_and_region()
    client = _s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": 'attachment; filename="video.mp4"',
        },
        ExpiresIn=expires_seconds,
    )

