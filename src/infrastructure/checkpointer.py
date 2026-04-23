"""Setup do checkpointer Redis para persistência do estado LangGraph.

Ver ADR-004 para justificativa da escolha do Redis.
Cada sessão Streamlit recebe um thread_id único.
"""
from __future__ import annotations

import logging

import redis
from langgraph.checkpoint.memory import MemorySaver

from src.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger(__name__)


def criar_checkpointer():
    """Tenta criar um RedisSaver. Fallback para MemorySaver se Redis indisponível.

    O fallback garante que o sistema funcione sem Redis durante desenvolvimento,
    mas loga um aviso para que o desenvolvedor saiba.
    """
    try:
        from langgraph.checkpoint.redis import RedisSaver

        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            decode_responses=False,
            socket_connect_timeout=2,
        )
        client.ping()
        logger.info("Redis conectado em %s:%s — usando RedisSaver", REDIS_HOST, REDIS_PORT)
        return RedisSaver(client)

    except Exception as exc:
        logger.warning(
            "Redis indisponível (%s). Usando MemorySaver — estado perdido ao reiniciar.",
            exc,
        )
        return MemorySaver()
