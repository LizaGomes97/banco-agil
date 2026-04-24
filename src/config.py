from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Raiz do projeto ───────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent

# ── LLM ──────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD: str | None = os.getenv("REDIS_PASSWORD") or None
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
REDIS_TTL_SECONDS: int = int(os.getenv("REDIS_TTL_SECONDS", "1800"))  # 30 min

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY") or None
QDRANT_EMBEDDING_DIMENSION: int = int(os.getenv("QDRANT_EMBEDDING_DIMENSION", "3072"))
QDRANT_MAX_CONCURRENT: int = int(os.getenv("QDRANT_MAX_CONCURRENT", "4"))
QDRANT_SCORE_THRESHOLD: float = float(os.getenv("QDRANT_SCORE_THRESHOLD", "0.5"))
GEMINI_API_KEY_EMBEDDINGS: str = os.getenv("GEMINI_API_KEY_EMBEDDINGS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")

# Chave dedicada do worker de curadoria — NÃO compete com o chat no rate limit.
# Se ausente, cai no GEMINI_API_KEY (ver ADR-023).
GEMINI_API_KEY_CURATOR: str = os.getenv("GEMINI_API_KEY_CURATOR", os.getenv("GEMINI_API_KEY", ""))

# ── Postgres (staging + observabilidade) ─────────────────────────────────────
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "banco_agil")
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

# ── Tavily ────────────────────────────────────────────────────────────────────
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

# ── Dados ─────────────────────────────────────────────────────────────────────
DATA_DIR: Path = ROOT_DIR / "data"
CLIENTES_CSV: Path = DATA_DIR / "clientes.csv"
SOLICITACOES_CSV: Path = DATA_DIR / "solicitacoes_aumento_limite.csv"
SCORE_LIMITE_CSV: Path = DATA_DIR / "score_limite.csv"

# ── Negócio ───────────────────────────────────────────────────────────────────
MAX_TENTATIVAS_AUTH: int = 3
SCORE_MINIMO_APROVACAO: int = 500
