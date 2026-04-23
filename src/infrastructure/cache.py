"""Cache L1 em memória para resultados de operações custosas.

Padrão adaptado do backend/core/cache.py do projeto anterior.
Usado principalmente para evitar chamadas LLM repetidas no classificador
de intenção quando o usuário envia mensagens idênticas ou muito similares.

Design: LRU simples com TTL por entrada. Thread-safe via functools.lru_cache
para o caso de uso mais comum (classificação de intenção).
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

import logging

logger = logging.getLogger(__name__)


class CacheComTTL:
    """Cache em memória com TTL por entrada e limite de tamanho (LRU simplificado).

    Não usa dependências externas — funciona sem Redis.
    Para cache distribuído entre sessões, usar Redis diretamente.
    """

    def __init__(self, ttl_segundos: int = 300, max_tamanho: int = 256):
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_segundos
        self._max = max_tamanho

    def get(self, chave: str) -> Any | None:
        """Retorna o valor se existir e não tiver expirado, senão None."""
        entrada = self._store.get(chave)
        if not entrada:
            return None
        valor, expira_em = entrada
        if time.monotonic() > expira_em:
            del self._store[chave]
            return None
        return valor

    def set(self, chave: str, valor: Any) -> None:
        """Armazena o valor com TTL. Remove a entrada mais antiga se atingir limite."""
        if len(self._store) >= self._max:
            chave_mais_antiga = next(iter(self._store))
            del self._store[chave_mais_antiga]
        self._store[chave] = (valor, time.monotonic() + self._ttl)

    def invalidar(self, chave: str) -> None:
        self._store.pop(chave, None)

    def limpar(self) -> None:
        self._store.clear()

    @property
    def tamanho(self) -> int:
        return len(self._store)


def com_cache(cache: CacheComTTL, chave_fn: Callable[..., str] | None = None):
    """Decorator que aplica cache a uma função usando CacheComTTL.

    Args:
        cache: Instância de CacheComTTL a usar.
        chave_fn: Função que deriva a chave de cache dos argumentos.
                  Se None, usa str(args) + str(kwargs).

    Exemplo:
        _cache = CacheComTTL(ttl_segundos=300)

        @com_cache(_cache, chave_fn=lambda msg: msg.strip().lower())
        def classificar_intencao(mensagem: str) -> str: ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            chave = chave_fn(*args, **kwargs) if chave_fn else str(args) + str(kwargs)
            cached = cache.get(chave)
            if cached is not None:
                logger.debug("Cache HIT para chave='%s'", chave[:50])
                return cached
            resultado = fn(*args, **kwargs)
            cache.set(chave, resultado)
            logger.debug("Cache MISS → armazenado para chave='%s'", chave[:50])
            return resultado
        return wrapper
    return decorator
