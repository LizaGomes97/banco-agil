"""Configuração centralizada de logging do Banco Ágil.

Grava em dois destinos simultaneamente:
  - Console (stdout) — nível INFO, formato compacto
  - Arquivo rotativo (logs/banco_agil.log) — nível DEBUG, formato completo

Uso nos módulos:
    from src.infrastructure.logging_config import get_logger
    logger = get_logger(__name__)
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "banco_agil.log"
_CONFIGURED = False


def setup_logging(level_console: int = logging.INFO) -> None:
    """Configura handlers de console e arquivo. Idempotente."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt_full = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt_short = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Console ───────────────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(level_console)
    console.setFormatter(fmt_short)

    # ── Arquivo rotativo (5 MB × 5 backups) ──────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt_full)

    root.addHandler(console)
    root.addHandler(file_handler)

    # Silencia loggers muito verbosos de bibliotecas externas
    for noisy in ("httpx", "httpcore", "urllib3", "google.auth"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Retorna logger configurado. Chame setup_logging() antes da primeira vez."""
    return logging.getLogger(name)


def tail_log(n: int = 100) -> list[str]:
    """Retorna as últimas N linhas do arquivo de log."""
    if not _LOG_FILE.exists():
        return ["(arquivo de log ainda não criado)"]
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception as exc:
        return [f"Erro ao ler log: {exc}"]
