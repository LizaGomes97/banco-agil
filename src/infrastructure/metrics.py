"""Métricas operacionais em processo — leves e thread-safe.

Propósito: dar visibilidade ao operador SEM depender de stack externa
(Prometheus, DataDog, etc). Expostas via GET /api/debug/metrics.

O que é medido:
  - chat.requests: total de POST /api/chat
  - chat.errors: erros do grafo
  - chat.latency_ms: histograma (p50/p95/p99) via lista circular
  - classificador: delegado para intent_classifier.obter_metricas()
  - feedback: contadores positivos/negativos recebidos

Não é substituto de APM. É diagnóstico para o próprio case e pra
permitir responder "a taxa de feedback negativo está caindo?"
sem precisar subir dashboard.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Deque


class MetricsStore:
    """Registro agregado de métricas em memória. Reset em cada restart."""

    def __init__(self, latency_window: int = 1000) -> None:
        self._lock = threading.Lock()
        self._contadores: Counter[str] = Counter()
        self._latencias: Deque[float] = deque(maxlen=latency_window)
        self._iniciado_em = time.time()

    # ── Contadores ─────────────────────────────────────────────────────────
    def incrementar(self, chave: str, valor: int = 1) -> None:
        with self._lock:
            self._contadores[chave] += valor

    def contador(self, chave: str) -> int:
        with self._lock:
            return self._contadores[chave]

    # ── Latência ──────────────────────────────────────────────────────────
    def registrar_latencia_ms(self, ms: float) -> None:
        with self._lock:
            self._latencias.append(ms)

    def _percentis(self) -> dict:
        with self._lock:
            if not self._latencias:
                return {"p50": None, "p95": None, "p99": None, "n": 0}
            ordenados = sorted(self._latencias)
            n = len(ordenados)

        def p(q: float) -> float:
            idx = min(n - 1, max(0, int(q * n) - 1))
            return round(ordenados[idx], 2)

        return {
            "p50": p(0.50),
            "p95": p(0.95),
            "p99": p(0.99),
            "n": n,
            "max": round(ordenados[-1], 2),
            "min": round(ordenados[0], 2),
        }

    # ── Snapshot ──────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        uptime = round(time.time() - self._iniciado_em, 1)
        with self._lock:
            contadores = dict(self._contadores)
        return {
            "uptime_seconds": uptime,
            "contadores": contadores,
            "latencia_ms": self._percentis(),
        }


metrics = MetricsStore()


class cronometro:
    """Context manager que registra latência de um bloco no MetricsStore.

    Uso:
        with cronometro("chat.latency_ms"):
            result = graph.invoke(...)
    """

    def __init__(self, chave: str, store: MetricsStore = metrics) -> None:
        self.chave = chave
        self.store = store
        self._t0 = 0.0

    def __enter__(self) -> "cronometro":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        dt_ms = (time.perf_counter() - self._t0) * 1000
        self.store.registrar_latencia_ms(dt_ms)
