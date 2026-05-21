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

## Modal + S3 (MVP)

Este repo incluye un deploy en Modal que:
- Encola renders con `POST /api/render/async`
- Renderiza con FFmpeg en un worker (fuera del request HTTP)
- Sube el MP4 a S3 y entrega una **presigned URL (24h)** para descarga
- Limita la concurrencia a **máx 4 renders simultáneos** vía `max_containers=4`

### 1) Instalar y configurar Modal

```bash
pip install modal
modal setup
```

### 2) Crear el Secret de S3 en Modal

Crea un secret llamado `render-s3` con:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (ej: `us-east-1`)
- `AWS_S3_BUCKET` (ej: `elearningninja`)

Ejemplo (rellena tus valores):

```bash
modal secret create render-s3 \
  AWS_ACCESS_KEY_ID="..." \
  AWS_SECRET_ACCESS_KEY="..." \
  AWS_REGION="us-east-1" \
  AWS_S3_BUCKET="elearningninja"
```

### 3) Deploy

```bash
modal deploy modal_app.py
```

Modal te mostrará una URL base para el servicio web. Úsala como `{BASE_URL}` en los curls.

### 4) Smoke tests (curl)

Crear job:

```bash
curl -X POST "{BASE_URL}/api/render/async" \
  -H "Content-Type: application/json" \
  -d @request.json
```

Consultar estado (repetir hasta `completed`):

```bash
curl "{BASE_URL}/api/render/{jobId}/status"
```

Descargar (redirige a presigned URL de S3):

```bash
curl -I "{BASE_URL}/api/render/{jobId}/download"
curl -L "{BASE_URL}/api/render/{jobId}/download" --output output.mp4
```

### 5) Test de concurrencia (máx 4 simultáneos)

Lanza 6 jobs en paralelo:

```bash
printf '%s\n' 1 2 3 4 5 6 | xargs -P 6 -I{} \
  curl -s -X POST "{BASE_URL}/api/render/async" -H "Content-Type: application/json" -d @request.json
```

Esperado:
- Solo 4 jobs avanzan a `processing` simultáneamente
- Los extras se quedan `queued` hasta que haya capacidad


---

## 🔧 Comandos de Testing Rápido

### PowerShell (Windows) - Modal

```powershell
# 1. SOLICITAR RENDER
$BASE_URL="https://patob2000--render-service-fastapi-app.modal.run"
$resp = curl.exe -s -X POST "$BASE_URL/api/render/async" `
  -H "Content-Type: application/json" `
  --data-binary "@request.json" | ConvertFrom-Json
$JOB_ID = $resp.jobId
Write-Host "Job ID: $JOB_ID"

# 2. MONITOREAR (loop hasta completar)
while($true) {
    $s = Invoke-RestMethod -Method Get -Uri "$BASE_URL/api/render/$JOB_ID/status"
    $s | ConvertTo-Json -Depth 10
    if($s.status -eq "completed"){
        Write-Host "✅ Completado!"
        break
    }
    if($s.status -eq "failed"){
        throw $s.error
    }
    Start-Sleep -Seconds 3
}

# 3. DESCARGAR
curl.exe -L "$BASE_URL/api/render/$JOB_ID/download" --output "output-$JOB_ID.mp4"
Write-Host "✅ Video descargado: output-$JOB_ID.mp4"
```

### CMD (Windows) - Modal

```cmd
set BASE_URL=https://patob2000--render-service-fastapi-app.modal.run

REM 1. Crear job
curl.exe -X POST "%BASE_URL%/api/render/async" ^
  -H "Content-Type: application/json" ^
  --data-binary "@request.json"

REM 2. Consultar estado (reemplaza JOB_ID)
curl.exe "%BASE_URL%/api/render/YOUR_JOB_ID/status"

REM 3. Descargar video
curl.exe -L "%BASE_URL%/api/render/YOUR_JOB_ID/download" --output output.mp4
```

### Bash (Linux/Mac) - Modal

```bash
BASE_URL="https://patob2000--render-service-fastapi-app.modal.run"

# 1. Crear job
RESPONSE=$(curl -s -X POST "$BASE_URL/api/render/async" \
  -H "Content-Type: application/json" \
  -d @request.json)
JOB_ID=$(echo $RESPONSE | jq -r '.jobId')
echo "Job ID: $JOB_ID"

# 2. Monitorear
while true; do
    STATUS=$(curl -s "$BASE_URL/api/render/$JOB_ID/status")
    echo $STATUS | jq '.'
    
    STATE=$(echo $STATUS | jq -r '.status')
    if [ "$STATE" = "completed" ]; then
        echo "✅ Completado!"
        break
    fi
    if [ "$STATE" = "failed" ]; then
        echo "❌ Falló"
        exit 1
    fi
    
    sleep 3
done

# 3. Descargar
curl -L "$BASE_URL/api/render/$JOB_ID/download" -o "output-$JOB_ID.mp4"
echo "✅ Video descargado"
```

---

## 🧪 Testing Local (sin Modal)

Si quieres probar el código localmente antes de deployar a Modal:

```bash
# 1. Ejecutar servidor local
python -m uvicorn app.main_simple:app --reload --port 4000

# 2. Health check
curl http://localhost:4000/health

# 3. Crear render
curl -X POST "http://localhost:4000/api/render/async" \
  -H "Content-Type: application/json" \
  --data-binary "@request.json"

# 4. Consultar estado (reemplaza JOB_ID)
curl "http://localhost:4000/api/render/YOUR_JOB_ID/status"

# 5. Descargar
curl -L "http://localhost:4000/api/render/YOUR_JOB_ID/download" --output output.mp4
```

**Windows CMD:**
```cmd
REM Health
curl.exe http://localhost:4000/health

REM Crear render
curl.exe -X POST "http://localhost:4000/api/render/async" ^
  -H "Content-Type: application/json" ^
  --data-binary "@request.json"

REM Status
curl.exe "http://localhost:4000/api/render/YOUR_JOB_ID/status"

REM Download
curl.exe -L "http://localhost:4000/api/render/YOUR_JOB_ID/download" --output output.mp4
```

