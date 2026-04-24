# Imagem única para API (FastAPI) e Worker Curador.
# O serviço escolhido é definido pelo CMD no docker-compose.
#
# Build: docker build -t banco-agil:latest .
# Run (api):    docker run -p 8000:8000 --env-file .env banco-agil:latest
# Run (worker): docker run --env-file .env banco-agil:latest python -m src.worker.curator --once

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Dependências do sistema (mínimo para gRPC do Qdrant + healthchecks) ───────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Instala dependências Python em camada separada (cache docker) ─────────────
COPY requirements.txt ./
# streamlit e pytest não são usados em produção — remove para poupar imagem/RAM
RUN grep -v -E '^(streamlit|pytest|pytest-asyncio)' requirements.txt > /tmp/req-prod.txt \
    && pip install --no-cache-dir -r /tmp/req-prod.txt

# ── Código da aplicação ───────────────────────────────────────────────────────
COPY api/ ./api/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY seeds/ ./seeds/
COPY data/ ./data/

# Usuário não-root
RUN useradd -m -u 1001 app && chown -R app:app /app
USER app

# Porta padrão do FastAPI
EXPOSE 8000

# Healthcheck simples — a API responde em /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# Default: sobe a API. Worker sobrescreve via compose/cron.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
