"""Memória semântica por cliente usando Qdrant.

Cada cliente tem suas memórias isoladas pelo campo `cpf` nos metadados.
Ao salvar, geramos um embedding do resumo da conversa e armazenamos no Qdrant.
Ao buscar, filtramos APENAS pelo CPF do cliente — nunca misturamos clientes.

Collection usada: banco_agil_memoria_cliente (criada em setup_qdrant.py)
Dimensão do vetor: 3072 (gemini-embedding-001)
"""
from __future__ import annotations

import logging
import uuid
import warnings
from datetime import date
from typing import Any

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.config import (
    GEMINI_API_KEY_EMBEDDINGS,
    GEMINI_EMBEDDING_MODEL,
    QDRANT_API_KEY,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

COLLECTION = "banco_agil_memoria_cliente"
_embeddings: GoogleGenerativeAIEmbeddings | None = None


def _get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Instância singleton do modelo de embeddings."""
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBEDDING_MODEL,
            google_api_key=GEMINI_API_KEY_EMBEDDINGS,
        )
    return _embeddings


def _get_client():
    from qdrant_client import QdrantClient
    # HTTP simples via tunnel SSH — o warning de "insecure connection" é esperado
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=10, https=False)


def salvar_interacao(
    cpf: str,
    resumo: str,
    agentes_usados: list[str] | None = None,
    resultado: str = "",
) -> bool:
    """Salva um resumo de interação no Qdrant com isolamento por CPF.

    Args:
        cpf: CPF do cliente — usado como chave de isolamento nos metadados.
        resumo: Texto descritivo da conversa (gerado pelo LLM).
        agentes_usados: Lista dos agentes que participaram da sessão.
        resultado: Resultado principal (ex: "limite aprovado", "score atualizado").

    Returns:
        True se salvou com sucesso, False em caso de erro.
    """
    try:
        from qdrant_client.models import PointStruct

        vetor = _get_embeddings().embed_query(resumo)
        ponto = PointStruct(
            id=str(uuid.uuid4()),
            vector=vetor,
            payload={
                "cpf": cpf,
                "resumo": resumo,
                "data": date.today().isoformat(),
                "agentes_usados": agentes_usados or [],
                "resultado": resultado,
            },
        )
        _get_client().upsert(collection_name=COLLECTION, points=[ponto])
        logger.info("Memória salva no Qdrant para CPF %s", cpf[-4:])
        return True
    except Exception as exc:
        logger.error("Erro ao salvar memória no Qdrant: %s", exc)
        return False


def buscar_memorias(cpf: str, consulta: str, top_k: int = 3) -> list[str]:
    """Busca memórias semânticas de um cliente específico.

    Filtra ESTRITAMENTE pelo CPF — nunca retorna dados de outros clientes.

    Args:
        cpf: CPF do cliente — filtro obrigatório.
        consulta: Texto da consulta (geralmente a última mensagem do usuário).
        top_k: Número máximo de memórias a retornar.

    Returns:
        Lista de resumos das interações anteriores mais relevantes.
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        vetor = _get_embeddings().embed_query(consulta)
        resposta = _get_client().query_points(
            collection_name=COLLECTION,
            query=vetor,
            query_filter=Filter(
                must=[FieldCondition(key="cpf", match=MatchValue(value=cpf))]
            ),
            limit=top_k,
            score_threshold=0.5,
        )
        memorias = [
            r.payload.get("resumo", "")
            for r in resposta.points
            if r.payload and r.payload.get("resumo")
        ]
        logger.info("Encontradas %d memórias para CPF %s", len(memorias), cpf[-4:])
        return memorias
    except Exception as exc:
        logger.error("Erro ao buscar memórias no Qdrant: %s", exc)
        return []
