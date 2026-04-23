"""
Logging do simulador de clientes — Banco Ágil.

Dois destinos:
  - Console  → nível INFO, formato compacto (o que você vê no terminal)
  - Arquivo  → nível DEBUG, formato completo (simulador/logs/simulador.log)

O arquivo de log é a fonte de verdade para diagnóstico:
    tail -n 100 simulador/logs/simulador.log
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_FILE = _LOG_DIR / "simulador.log"
_CONFIGURED = False


def setup_logging(verbose_console: bool = False) -> None:
    """Configura logging do simulador. Idempotente."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("simulador")
    root.setLevel(logging.DEBUG)
    root.propagate = False  # não polui o logger raiz

    fmt_console = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_arquivo = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console: INFO por padrão, DEBUG se --verbose
    console_level = logging.DEBUG if verbose_console else logging.INFO
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(fmt_console)

    # Arquivo rotativo: sempre DEBUG (tudo)
    arquivo = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    arquivo.setLevel(logging.DEBUG)
    arquivo.setFormatter(fmt_arquivo)

    root.addHandler(console)
    root.addHandler(arquivo)

    _CONFIGURED = True


def get_logger(nome: str) -> logging.Logger:
    return logging.getLogger(f"simulador.{nome}")
