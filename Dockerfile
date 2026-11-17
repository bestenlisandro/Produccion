FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN VITE_CLOUD_BUILD=true npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src/production_besten ./src/production_besten
COPY --from=frontend /build/dist ./frontend/dist
USER 10001:10001
CMD ["sh", "-c", "exec python -m uvicorn production_besten.api.cloud:create_cloud_app --factory --host 0.0.0.0 --port \"${PORT:-10000}\""]
