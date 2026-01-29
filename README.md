"""
Guía mínima para probar el backend de render aislado.

Este directorio es una copia mínima del servicio simple (sin Celery/Redis),
pensado para ejecutar en un servidor distinto y probar con curl.
"""

# Render Service Minimal (sin Celery)

## 1) Requisitos
- Python 3.11+
- FFmpeg instalado en el sistema

## 2) Instalación
```bash
cd render-service-minimal
pip install -r requirements.txt
```

## 3) Ejecutar
```bash
python -m uvicorn app.main_simple:app --reload --port 4000
```

## 4) Probar health
```bash
curl http://localhost:4000/health
```

## 5) Probar render async con 2 slides (curl)
> Reemplaza las URLs de `backgroundImage` y `avatarVideo` por archivos accesibles.

```bash
curl -X POST http://localhost:4000/api/render/async \
  -H "Content-Type: application/json" \
  -d "{\
    \"projectName\": \"Demo\",\
    \"slides\": [\
      {\
        \"index\": 0,\
        \"titulo\": \"Slide 1\",\
        \"backgroundImage\": \"https://example.com/bg1.png\",\
        \"audioNarration\": \"https://example.com/audio1.mp3\"\
      },\
      {\
        \"index\": 1,\
        \"titulo\": \"Slide 2\",\
        \"backgroundImage\": \"https://example.com/bg2.png\",\
        \"avatarVideo\": \"https://example.com/avatar.mp4\",\
        \"duration\": 5\
      }\
    ],\
    \"resolution\": \"1080p\",\
    \"fps\": 30,\
    \"quality\": \"high\"\
  }"
```

Respuesta esperada:
```json
{
  "jobId": "...",
  "status": "processing",
  "statusUrl": "/api/render/{jobId}/status"
}
```

## 6) Consultar estado
```bash
curl http://localhost:4000/api/render/{jobId}/status
```

## 7) Descargar video
```bash
curl -L http://localhost:4000/api/render/{jobId}/download --output output.mp4
```
