"""Interface unificada de memória aprendida (golden + worker).

Fornece 3 funções síncronas para o hot path do LangGraph:

  - buscar_routing_similar:    k-NN em learned_routing (usado pelo intent_classifier)
  - buscar_templates_similar:  k-NN em learned_templates (usado pelos agentes)
  - obter_regras_ativas_sync:  regras textuais de curator_lessons (filtradas por agente)

Ver ADR-023 — "Memória de Padrões (Golden Set + Source Tag)".

Princípios:
  - Síncrono (os nós do grafo são síncronos por padrão).
  - Falha silenciosa — memória é opcional; agente funciona sem ela.
  - Boost golden aplicado no score.
  - Cache curto em memória nas regras (SQLite, hit frequente, mudança rara).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import warnings
from functools import lru_cache
from pathlib import Path

from src.config import (
    GEMINI_API_KEY_EMBEDDINGS,
    GEMINI_EMBEDDING_MODEL,
    QDRANT_API_KEY,
    QDRANT_URL,
    ROOT_DIR,
)
from src.infrastructure.vector_store import (
    COLLECTION_LEARNED_ROUTING,
    COLLECTION_LEARNED_TEMPLATES,
    GOLDEN_SCORE_BOOST,
    SOURCE_GOLDEN,
)

logger = logging.getLogger(__name__)

_DB_PATH: Path = ROOT_DIR / "data" / "banco_agil.db"

_ROUTING_SCORE_THRESHOLD = 0.60   # pré-boost; golden boostado costuma passar de 1.0
_ROUTING_SHORTCUT_SCORE = 1.10    # se score (pós-boost) >= isto, pula o LLM
_TEMPLATES_SCORE_THRESHOLD = 0.55
_TEMPLATES_TOP_K_DEFAULT = 2
_ROUTING_TOP_K_DEFAULT = 3

# ── Cliente Qdrant (síncrono, singleton) ──────────────────────────────────
_qdrant_client = None
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        _embedder = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBEDDING_MODEL,
            google_api_key=GEMINI_API_KEY_EMBEDDINGS,
        )
    return _embedder


def _get_client():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _qdrant_client = QdrantClient(
                url=QDRANT_URL,
                api_key=QDRANT_API_KEY or None,
                timeout=10,
                https=False,
            )
    return _qdrant_client


@lru_cache(maxsize=256)
def _embed_cached(query: str) -> tuple[float, ...]:
    return tuple(_get_embedder().embed_query(query))


def _aplicar_boost(score: float, source: str | None) -> float:
    if source == SOURCE_GOLDEN:
        return score + GOLDEN_SCORE_BOOST
    return score


# ── Routing (intent_classifier) ───────────────────────────────────────────

def buscar_routing_similar(
    mensagem: str,
    k: int = _ROUTING_TOP_K_DEFAULT,
) -> list[dict]:
    """k-NN em learned_routing. Retorna lista ordenada por score (pós-boost) desc.

    Cada item: {intent, agente, exemplo, score, source, nota}.
    Em qualquer falha, retorna lista vazia (memória é opcional).
    """
    texto = (mensagem or "").strip()
    if not texto:
        return []
    try:
        vector = list(_embed_cached(texto))
        resp = _get_client().query_points(
            collection_name=COLLECTION_LEARNED_ROUTING,
            query=vector,
            limit=max(k, 1),
            with_payload=True,
            score_threshold=_ROUTING_SCORE_THRESHOLD,
        )
    except Exception as exc:
        logger.debug("learned_memory.routing: indisponível (%s) — sem hits", exc)
        return []

    resultados: list[dict] = []
    for point in getattr(resp, "points", []):
        p = point.payload or {}
        source = p.get("source")
        resultados.append({
            "intent": p.get("intent"),
            "agente": p.get("agente"),
            "exemplo": p.get("text") or "",
            "source": source,
            "nota": p.get("nota") or "",
            "score": _aplicar_boost(point.score, source),
        })
    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados[:k]


def sugerir_intent_direto(mensagem: str) -> str | None:
    """Atalho: se o top hit de routing for muito forte, retorna o intent direto.

    Retorna None se o sinal não é forte o suficiente — aí o caller chama o LLM normal.
    """
    hits = buscar_routing_similar(mensagem, k=1)
    if not hits:
        return None
    top = hits[0]
    if top["score"] >= _ROUTING_SHORTCUT_SCORE and top.get("intent"):
        logger.info(
            "learned_memory.routing: shortcut intent=%s score=%.3f source=%s",
            top["intent"], top["score"], top.get("source"),
        )
        return top["intent"]
    return None


# ── Templates (agentes) ───────────────────────────────────────────────────

def buscar_templates_similar(
    mensagem: str,
    intent: str | None = None,
    agente: str | None = None,
    k: int = _TEMPLATES_TOP_K_DEFAULT,
) -> list[dict]:
    """k-NN em learned_templates com filtro opcional por intent/agente.

    Cada item: {tmpl_id, intent, agente, situacao, esqueleto, placeholders,
                tool_fonte, evitar, score, source}.
    """
    texto = (mensagem or "").strip()
    if not texto:
        return []
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        vector = list(_embed_cached(texto))
        must: list = []
        if intent:
            must.append(FieldCondition(key="intent", match=MatchValue(value=intent)))
        if agente:
            must.append(FieldCondition(key="agente", match=MatchValue(value=agente)))
        query_filter = Filter(must=must) if must else None

        resp = _get_client().query_points(
            collection_name=COLLECTION_LEARNED_TEMPLATES,
            query=vector,
            query_filter=query_filter,
            limit=max(k, 1),
            with_payload=True,
            score_threshold=_TEMPLATES_SCORE_THRESHOLD,
        )
    except Exception as exc:
        logger.debug("learned_memory.templates: indisponível (%s) — sem hits", exc)
        return []

    resultados: list[dict] = []
    for point in getattr(resp, "points", []):
        p = point.payload or {}
        source = p.get("source")
        try:
            placeholders = json.loads(p.get("placeholders") or "[]")
        except (TypeError, ValueError):
            placeholders = []
        try:
            evitar = json.loads(p.get("evitar") or "[]")
        except (TypeError, ValueError):
            evitar = []
        resultados.append({
            "tmpl_id": p.get("tmpl_id") or p.get("doc_id") or "",
            "intent": p.get("intent"),
            "agente": p.get("agente"),
            "situacao": p.get("situacao") or "",
            "esqueleto": p.get("esqueleto") or "",
            "placeholders": placeholders,
            "tool_fonte": p.get("tool_fonte") or "",
            "evitar": evitar,
            "source": source,
            "score": _aplicar_boost(point.score, source),
        })
    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados[:k]


def formatar_template_para_prompt(tmpl: dict) -> str:
    """Converte um template em bloco de texto pronto para injetar no system prompt."""
    partes = [f"**Situação:** {tmpl.get('situacao', '')}"]
    esqueleto = tmpl.get("esqueleto") or ""
    if esqueleto:
        partes.append(f"**Formato sugerido (com placeholders):**\n{esqueleto}")
    tool = tmpl.get("tool_fonte")
    if tool:
        partes.append(f"**Tool obrigatória para preencher placeholders:** `{tool}`")
    evitar = tmpl.get("evitar") or []
    if evitar:
        partes.append("**Evitar:** " + "; ".join(evitar))
    return "\n".join(partes)


def buscar_templates_formatados(
    mensagem: str,
    intent: str | None = None,
    agente: str | None = None,
    k: int = _TEMPLATES_TOP_K_DEFAULT,
) -> list[str]:
    """Atalho: busca templates e já retorna como lista de strings formatadas.

    Usado pelo `few_shot.buscar_exemplos_curados` (adaptador de compatibilidade).
    """
    hits = buscar_templates_similar(mensagem, intent=intent, agente=agente, k=k)
    return [formatar_template_para_prompt(h) for h in hits]


# ── Regras ativas (curator_lessons) ───────────────────────────────────────
# Cache curto em memória: SQLite local é rápido, mas evitar hit a cada turno.

_regras_cache_lock = threading.Lock()
_regras_cache: dict[str, tuple[float, list[dict]]] = {}
_REGRAS_CACHE_TTL = 60.0  # segundos


def _consultar_regras_sqlite(agente: str | None) -> list[dict]:
    if not _DB_PATH.exists():
        return []
    sql = """
        SELECT id, example_text, source, aplicavel_a, motivo, ativa, created_at
        FROM curator_lessons
        WHERE ativa = 1
    """
    params: list = []
    if agente:
        sql += " AND (aplicavel_a LIKE ? OR aplicavel_a IS NULL)"
        params.append(f'%"{agente}"%')
    sql += " ORDER BY CASE source WHEN 'golden' THEN 0 ELSE 1 END, created_at DESC"
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, tuple(params))
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug("learned_memory.regras: falha SQL (%s)", exc)
        return []

    resultado: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["aplicavel_a"] = json.loads(d.get("aplicavel_a") or "[]")
        except (TypeError, ValueError):
            d["aplicavel_a"] = []
        d["ativa"] = bool(d.get("ativa"))
        d["regra"] = d.pop("example_text", "")
        resultado.append(d)
    return resultado


def obter_regras_ativas_sync(agente: str | None = None) -> list[dict]:
    """Retorna regras ativas para um agente (com cache de 60s)."""
    chave = agente or "__all__"
    agora = time.time()
    with _regras_cache_lock:
        entry = _regras_cache.get(chave)
        if entry and (agora - entry[0]) < _REGRAS_CACHE_TTL:
            return entry[1]
    regras = _consultar_regras_sqlite(agente)
    with _regras_cache_lock:
        _regras_cache[chave] = (agora, regras)
    return regras


def formatar_regras_para_prompt(regras: list[dict]) -> str:
    """Formata lista de regras como bloco de bullets para o system prompt."""
    if not regras:
        return ""
    linhas = ["\n\n## Regras ativas (memória destilada)"]
    linhas.append(
        "Estas regras foram extraídas de curadoria humana e/ou casos reais. "
        "SEMPRE respeite, mesmo que contradigam o estilo natural do modelo."
    )
    for r in regras:
        marca = "★" if r.get("source") == SOURCE_GOLDEN else "·"
        linhas.append(f"- {marca} {r['regra']}")
    return "\n".join(linhas)


def invalidar_cache_regras() -> None:
    """Chame após salvar uma nova regra (ex.: ao final do worker)."""
    with _regras_cache_lock:
        _regras_cache.clear()
