# syntax=docker/dockerfile:1
#
# Multi-stage build. The frontend is compiled to static assets and copied into
# the API image, which serves both the SPA and the JSON API from one origin.
# Build context is the repository ROOT:  docker build -f backend/Dockerfile .

# --- Stage 1: build the React SPA ------------------------------------------ #
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
# Emit into a local ./dist (overrides the dev outDir which points at the backend).
RUN npm run build -- --outDir dist --emptyOutDir

# --- Stage 2: Python runtime ----------------------------------------------- #
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# curl is used by the container HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
# Drop the built SPA where FastAPI serves it from.
COPY --from=frontend /fe/dist ./app/static

# Run as a non-root user.
#
# /app/data se crea AQUI, con su dueno puesto, aunque la imagen no guarde nada
# dentro. El motivo: cuando se monta un volumen con nombre sobre una ruta que NO
# existe en la imagen, Docker crea el directorio como root, y este contenedor
# corre como el usuario 10001 — no podria escribir su base de datos y el arranque
# que documentamos en el README fallaria en la primera linea. Si la ruta ya
# existe en la imagen, el volumen hereda su dueno y sus permisos, que es lo que
# queremos. Es la diferencia entre "docker run y listo" y un informe de fallo.
RUN useradd -m -u 10001 rackmon && mkdir -p /app/data && chown -R rackmon:rackmon /app
USER rackmon

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
