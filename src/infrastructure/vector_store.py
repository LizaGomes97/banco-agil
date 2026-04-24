"""Armazenamento vetorial Qdrant — camada única, async, multi-collection.

Usa `qdrant_client.AsyncQdrantClient` + `GoogleGenerativeAIEmbeddings`.

Collections ATIVAS (ver ADR-023):
  - learned_routing:   exemplos de roteamento (input -> intent/agente)
  - learned_templates: esqueletos de resposta com placeholders

As coleções legadas (`banco_agil_memoria_cliente`, `banco_agil_interacoes_curadas`,
`banco_agil_feedbacks_negativos`) foram desativadas: padrões concretos com PII
ou valores voláteis de cliente levavam a alucinação em respostas futuras.
Os nomes ficam expostos em `LEGACY_COLLECTION_NAMES` apenas para scripts de
limpeza (`scripts/reset_learning_data.py --legacy`).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
from typing import Any

from src.config import (
    GEMINI_API_KEY_EMBEDDINGS,
    GEMINI_EMBEDDING_MODEL,
    QDRANT_API_KEY,
    QDRANT_EMBEDDING_DIMENSION,
    QDRANT_MAX_CONCURRENT,
    QDRANT_SCORE_THRESHOLD,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

# ── Coleções da arquitetura de memória (ADR-023) ─────────────────────────
# Única memória semântica ativa: padrões abstratos (routing + templates).
# Não guardam PII nem valores de cliente — a fonte de dados reais são as tools.
COLLECTION_LEARNED_ROUTING = "banco_agil_learned_routing"
COLLECTION_LEARNED_TEMPLATES = "banco_agil_learned_templates"

# ── Coleções legadas (removidas em <data da remoção>) ────────────────────
# Mantemos os nomes como constantes para scripts de limpeza ainda acharem
# e purgarem caso a instância do Qdrant tenha resíduo antigo. Novos códigos
# NÃO devem usar — runtime escreve/lê apenas nas coleções "learned_*".
COLLECTION_MEMORIA_CLIENTE = "banco_agil_memoria_cliente"  # DEPRECATED
COLLECTION_CURADAS = "banco_agil_interacoes_curadas"         # DEPRECATED
COLLECTION_FEEDBACK_NEG = "banco_agil_feedbacks_negativos"   # DEPRECATED

# Origens possíveis de um padrão (payload.source)
SOURCE_GOLDEN = "golden"   # curado por humano, fonte de verdade
SOURCE_WORKER = "worker"   # aprendido automaticamente; boostado menos

# Boost aplicado ao score quando source == golden (ranking em k-NN misto)
GOLDEN_SCORE_BOOST = 0.25

# Apenas as learned_* são (re)criadas automaticamente pelo VectorStore.
COLLECTION_NAMES = [
    COLLECTION_LEARNED_ROUTING,
    COLLECTION_LEARNED_TEMPLATES,
]

# Coleções legadas — scripts de reset/limpeza usam este set para purgar.
LEGACY_COLLECTION_NAMES = [
    COLLECTION_MEMORIA_CLIENTE,
    COLLECTION_CURADAS,
    COLLECTION_FEEDBACK_NEG,
]

# Semáforo global — limita requisições concorrentes ao Qdrant sob carga.
# Evita timeout quando múltiplos clientes usam o chat ao mesmo tempo.
_semaforo = asyncio.Semaphore(QDRANT_MAX_CONCURRENT)
logger.info("VectorStore semaphore: max_concurrent=%d", QDRANT_MAX_CONCURRENT)


def _to_point_id(doc_id: str) -> str:
    """Converte doc_id string em UUID válido (determinístico).

    Qdrant aceita apenas UUID ou inteiro como point ID. Se `doc_id` já é
    UUID, retorna como está. Senão, deriva UUID5 do próprio string —
    garantindo que o mesmo doc_id sempre mapeie pro mesmo ponto.
    """
    try:
        return str(uuid.UUID(doc_id))
    except (ValueError, TypeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))


class VectorStore:
    """Armazenamento vetorial Qdrant com interface assíncrona.

    Instância única; use `vector_store` exportado no final do módulo.
    """

    def __init__(self) -> None:
        self._client: Any = None  # lazy — evita conectar se nunca for usado
        self._embedder: Any = None
        self._initialized = False
        self._dimension = QDRANT_EMBEDDING_DIMENSION
        self._init_lock = asyncio.Lock()

    # ── Inicialização lazy ─────────────────────────────────────────────────

    def _get_embedder(self):
        if self._embedder is None:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            self._embedder = GoogleGenerativeAIEmbeddings(
                model=GEMINI_EMBEDDING_MODEL,
                google_api_key=GEMINI_API_KEY_EMBEDDINGS,
            )
        return self._embedder

    def _get_client(self):
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._client = AsyncQdrantClient(
                    url=QDRANT_URL,
                    api_key=QDRANT_API_KEY or None,
                    timeout=30,
                    https=False,
                )
            logger.info(
                "VectorStore configurado | url=%s | dim=%d | collections=%s",
                QDRANT_URL,
                self._dimension,
                COLLECTION_NAMES,
            )
        return self._client

    async def _ensure_collections(self) -> None:
        """Garante que todas as collections existem. Idempotente."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            from qdrant_client.models import Distance, VectorParams

            client = self._get_client()
            for name in COLLECTION_NAMES:
                try:
                    exists = await client.collection_exists(name)
                    if not exists:
                        await client.create_collection(
                            collection_name=name,
                            vectors_config=VectorParams(
                                size=self._dimension,
                                distance=Distance.COSINE,
                            ),
                        )
                        logger.info("Collection '%s' criada no Qdrant", name)
                except Exception:
                    logger.exception("Erro ao verificar/criar collection '%s'", name)
                    raise
            self._initialized = True

    def _validate_collection(self, collection: str) -> None:
        if collection not in COLLECTION_NAMES:
            raise ValueError(
                f"Collection '{collection}' não reconhecida. "
                f"Válidas: {COLLECTION_NAMES}"
            )

    async def _embed(self, text: str) -> list[float]:
        """Gera embedding — roda em thread pool porque a lib langchain é síncrona."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_embedder().embed_query, text)

    # ── API pública ────────────────────────────────────────────────────────

    async def add_document(
        self,
        collection: str,
        text: str,
        metadata: dict,
        doc_id: str | None = None,
    ) -> str:
        """Adiciona documento (com embedding) a uma collection.

        Retorna o doc_id (gerado ou informado). Levanta em falha.
        """
        await self._ensure_collections()
        self._validate_collection(collection)

        from qdrant_client.models import PointStruct

        doc_id = doc_id or str(uuid.uuid4())
        point_id = _to_point_id(doc_id)
        vector = await self._embed(text)

        safe_meta = {k: ("" if v is None else v) for k, v in metadata.items()}
        payload = {"text": text, "doc_id": doc_id, **safe_meta}

        async with _semaforo:
            try:
                await self._get_client().upsert(
                    collection_name=collection,
                    points=[PointStruct(id=point_id, vector=vector, payload=payload)],
                )
                logger.debug(
                    "QDRANT UPSERT OK | collection=%s | doc_id=%s | texto=%.80s",
                    collection, doc_id, text,
                )
            except Exception:
                logger.exception(
                    "QDRANT UPSERT FALHOU | collection=%s | doc_id=%s",
                    collection, doc_id,
                )
                raise
        return doc_id

    async def search(
        self,
        collection: str,
        query: str,
        n_results: int = 5,
        where: dict | None = None,
        score_threshold: float | None = None,
        boost_source: str | None = SOURCE_GOLDEN,
        boost_amount: float = GOLDEN_SCORE_BOOST,
    ) -> list[dict]:
        """Busca semântica. Retorna lista de dicts com `text`, `metadata`, `score`.

        boost_source:  se o payload tiver source == boost_source, aplica `boost_amount`
                       ao score antes de reordenar. Default: boost em 'golden'.
                       Passe None para desligar o boost (ex.: busca em memória sem
                       distinção golden/worker).
        """
        await self._ensure_collections()
        self._validate_collection(collection)

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_vector = await self._embed(query)

        query_filter = None
        if where:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in where.items()
            ]
            query_filter = Filter(must=conditions)

        async with _semaforo:
            response = await self._get_client().query_points(
                collection_name=collection,
                query=query_vector,
                query_filter=query_filter,
                limit=n_results,
                with_payload=True,
                score_threshold=(
                    score_threshold if score_threshold is not None
                    else QDRANT_SCORE_THRESHOLD
                ),
            )

        results = []
        for point in response.points:
            payload = point.payload or {}
            score = point.score
            if boost_source and payload.get("source") == boost_source:
                score = score + boost_amount
            results.append({
                "text": payload.get("text", ""),
                "metadata": {
                    k: v for k, v in payload.items() if k not in ("text", "doc_id")
                },
                "score": score,
                "doc_id": payload.get("doc_id", ""),
            })
        # Reordena em ordem decrescente caso boost tenha mudado posições
        if boost_source:
            results.sort(key=lambda r: r["score"], reverse=True)
        return results

    async def delete_document(self, collection: str, doc_id: str) -> None:
        """Remove um ponto da collection."""
        await self._ensure_collections()
        self._validate_collection(collection)

        from qdrant_client.models import PointIdsList

        point_id = _to_point_id(doc_id)
        async with _semaforo:
            await self._get_client().delete(
                collection_name=collection,
                points_selector=PointIdsList(points=[point_id]),
            )

    async def count(self, collection: str) -> int:
        """Conta quantos pontos há em uma collection. 0 se não existir."""
        await self._ensure_collections()
        self._validate_collection(collection)
        try:
            async with _semaforo:
                result = await self._get_client().count(
                    collection_name=collection, exact=True,
                )
            return int(getattr(result, "count", 0) or 0)
        except Exception:
            logger.exception("Falha ao contar pontos em %s", collection)
            return 0

    async def listar_pontos(
        self,
        collection: str,
        limit: int = 50,
    ) -> list[dict]:
        """Lista pontos de uma collection (sem busca semântica).

        Para inspeção/auditoria do que está no Qdrant. Retorna payload + doc_id.
        Não retorna o vetor (payload puro, mais leve).
        """
        await self._ensure_collections()
        self._validate_collection(collection)

        pontos: list[dict] = []
        try:
            async with _semaforo:
                response, _next = await self._get_client().scroll(
                    collection_name=collection,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
            for p in response:
                payload = p.payload or {}
                pontos.append({
                    "doc_id": payload.get("doc_id") or str(p.id),
                    "text": payload.get("text", ""),
                    "metadata": {
                        k: v for k, v in payload.items() if k not in ("text", "doc_id")
                    },
                })
        except Exception:
            logger.exception("Falha ao listar pontos em %s", collection)
        return pontos

    async def close(self) -> None:
        """Fecha o client — útil em testes e shutdown do worker."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.exception("Erro ao fechar VectorStore")
            self._client = None
            self._initialized = False


# Instância compartilhada — preferir via `from src.infrastructure.vector_store import vector_store`
vector_store = VectorStore()
