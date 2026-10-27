# syntax=docker/dockerfile:1.7
# Build context: repository root (the API depends on the ml/ package).
#   docker build -f backend/Dockerfile -t sentinel-api .

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY backend/requirements.txt backend/requirements.txt
COPY ml ml
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r backend/requirements.txt ./ml

FROM python:3.12-slim AS runtime
# Apply Debian security updates so the image does not ship known-fixed CVEs.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin sentinel
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTINEL_MODEL_DIR=/app/ml/artifacts
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app/backend
COPY backend/ /app/backend/
COPY ml/artifacts /app/ml/artifacts
USER 10001
EXPOSE 8000
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", \
     "--workers", "2", "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-"]
