# One image: the API, the job worker and the PWA the phone loads.
#
# No credentials are baked in. On Cloud Run the attached service account
# provides identity through Application Default Credentials (PRD 40).

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# FFmpeg va DENTRO de la imagen del servicio: el montaje final se renderiza
# en este mismo proceso (assembly/engine.py), y sin el binario la app solo
# podia entregar el plan de montaje (EDL), nunca el MP4. Es el arreglo que
# hace real el boton de montar en produccion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/seed ./seed
COPY --from=web /web/dist ./frontend/dist

ENV AAUS_STATIC_DIR=/app/frontend/dist \
    PORT=8080

EXPOSE 8080
# --forwarded-allow-ips: sin esto uvicorn solo se fia de las cabeceras
# X-Forwarded-* que vengan de 127.0.0.1, y en Cloud Run vienen del frontal
# de Google desde una IP interna cualquiera. El resultado es que la app se
# cree en http estando en https, y la cookie de sesion pierde su marca
# Secure sin que nada falle a la vista. Al contenedor no se llega mas que
# por ese frontal, que reescribe esas cabeceras.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 \
    --timeout-keep-alive 75 --proxy-headers --forwarded-allow-ips='*'
