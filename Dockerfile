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
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/seed ./seed
COPY --from=web /web/dist ./frontend/dist

ENV AAUS_STATIC_DIR=/app/frontend/dist \
    PORT=8080

EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75
