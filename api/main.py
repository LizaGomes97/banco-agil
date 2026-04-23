"""FastAPI bridge — conecta o frontend React ao grafo LangGraph do Banco Ágil.

Contrato de API (consumido por frontend/src/app/services/api.ts):
  POST /api/chat                → invoca o grafo e retorna a resposta do agente
  GET  /api/conversations       → lista sessões armazenadas no Redis
  POST /api/conversations       → cria nova sessão
  GET  /api/conversations/{id}  → retorna mensagens de uma sessão
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from src.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from src.graph import get_graph
from src.infrastructure.logging_config import setup_logging, tail_log
from src.middleware.guardrails import Severidade, input_runner, output_runner

setup_logging()
logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Banco Ágil – API do Agente IA",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis para metadados de sessão ─────────────────────────────────────────────
def _redis_client() -> redis_lib.Redis:
    return redis_lib.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=2,
    )


# ── Helpers de sessão ──────────────────────────────────────────────────────────
_SESSIONS_KEY = "ba:sessions"          # sorted set com timestamps
_SESSION_META  = "ba:session:{sid}"    # hash com title, created_at, updated_at


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_meta(r: redis_lib.Redis, sid: str) -> dict | None:
    meta = r.hgetall(_SESSION_META.format(sid=sid))
    return meta if meta else None


def _save_meta(r: redis_lib.Redis, sid: str, title: str, updated: str, created: str | None = None) -> None:
    key = _SESSION_META.format(sid=sid)
    now = _now_iso()
    r.hset(key, mapping={
        "id": sid,
        "title": title,
        "created_at": created or now,
        "updated_at": updated,
    })
    r.zadd(_SESSIONS_KEY, {sid: datetime.fromisoformat(updated).timestamp()})


def _list_sessions(r: redis_lib.Redis, limit: int = 50) -> list[dict]:
    sids = r.zrevrange(_SESSIONS_KEY, 0, limit - 1)
    out = []
    for sid in sids:
        meta = _get_meta(r, sid)
        if meta:
            out.append(meta)
    return out


# ── Extrai mensagens do estado LangGraph ───────────────────────────────────────
def _extract_messages(state_values: dict) -> list[dict]:
    msgs = state_values.get("messages", [])
    out = []
    for i, m in enumerate(msgs):
        if isinstance(m, HumanMessage):
            out.append({
                "id": str(i),
                "role": "user",
                "content": m.content,
                "created_at": _now_iso(),
            })
        elif isinstance(m, AIMessage) and m.content:
            out.append({
                "id": str(i),
                "role": "assistant",
                "content": m.content,
                "created_at": _now_iso(),
            })
    return out


# ── Schemas ────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    authenticated: bool
    encerrado: bool


class CreateConversationRequest(BaseModel):
    title: str = "Nova conversa"


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Envia uma mensagem para o agente LangGraph e retorna a resposta."""
    graph = get_graph()
    sid = req.conversation_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": sid}}

    logger.info("[CHAT] session=%s | msg=%.80s", sid[:8], req.message)

    # ── Guardrails de INPUT ─────────────────────────────────────────────────
    input_check = input_runner.executar(req.message)
    if not input_check.aprovado and input_check.severidade in (
        Severidade.CRITICO, Severidade.ALTO
    ):
        logger.warning(
            "[CHAT] input bloqueado | severidade=%s motivo=%s",
            input_check.severidade,
            input_check.motivo,
        )
        return ChatResponse(
            reply=input_check.mensagem_cliente or "Não consigo processar essa solicitação.",
            conversation_id=sid,
            authenticated=False,
            encerrado=False,
        )

    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
        )
    except Exception as exc:
        logger.error("[CHAT] Erro ao invocar grafo: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno do agente: {exc}") from exc

    # Lê o contrato explícito de saída dos agentes (resposta_final).
    reply = (result.get("resposta_final") or "").strip()
    logger.debug("[CHAT] resposta_final bruta: %.200s", reply or "(vazio)")

    # Fallback defensivo: se resposta_final não foi setado, extrai da última AIMessage.
    if not reply:
        logger.warning("[CHAT] resposta_final vazia — usando fallback via messages")
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            if not isinstance(m, AIMessage):
                continue
            if getattr(m, "tool_calls", None) or m.additional_kwargs.get("tool_calls"):
                logger.debug("[CHAT] fallback: pulando AIMessage com tool_calls")
                continue
            content = (m.content or "").strip()
            if content:
                reply = content
                logger.debug("[CHAT] fallback: usando content=%.100s", content)
                break

    if not reply:
        reply = "Desculpe, não consegui processar sua solicitação. Tente novamente."

    # ── Guardrails de OUTPUT ────────────────────────────────────────────────
    output_check = output_runner.executar(reply)
    if not output_check.aprovado and output_check.severidade in (
        Severidade.CRITICO, Severidade.ALTO
    ):
        logger.warning(
            "[CHAT] output bloqueado | severidade=%s motivo=%s",
            output_check.severidade,
            output_check.motivo,
        )
        reply = output_check.mensagem_cliente or "Não consigo processar essa solicitação."

    # Atualiza metadados da sessão no Redis
    try:
        r = _redis_client()
        meta = _get_meta(r, sid)
        created = meta["created_at"] if meta else _now_iso()
        # Usa o início da mensagem do usuário como título se for nova sessão
        title = meta["title"] if meta else (req.message[:50] + "..." if len(req.message) > 50 else req.message)
        _save_meta(r, sid, title=title, updated=_now_iso(), created=created)
    except Exception as e:
        logger.warning("Não foi possível salvar metadados da sessão: %s", e)

    authenticated = bool(result.get("cliente_autenticado"))
    encerrado = bool(result.get("encerrado"))
    logger.info("[CHAT] authenticated=%s encerrado=%s reply=%.60s", authenticated, encerrado, reply)
    return ChatResponse(reply=reply, conversation_id=sid, authenticated=authenticated, encerrado=encerrado)


@app.get("/api/conversations")
async def list_conversations():
    """Lista todas as sessões de conversa."""
    try:
        r = _redis_client()
        sessions = _list_sessions(r)
        return {"sessions": sessions}
    except Exception as e:
        logger.warning("Erro ao listar sessões: %s", e)
        return {"sessions": []}


@app.post("/api/conversations")
async def create_conversation(req: CreateConversationRequest):
    """Cria uma nova sessão de conversa."""
    sid = str(uuid.uuid4())
    now = _now_iso()
    try:
        r = _redis_client()
        _save_meta(r, sid, title=req.title, updated=now, created=now)
    except Exception as e:
        logger.warning("Erro ao criar sessão no Redis: %s", e)

    return {"id": sid, "title": req.title, "updated_at": now, "created_at": now}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Retorna o histórico de mensagens de uma conversa."""
    graph = get_graph()
    config = {"configurable": {"thread_id": conversation_id}}

    try:
        state = graph.get_state(config)
        messages = _extract_messages(state.values) if state.values else []
    except Exception as e:
        logger.error("Erro ao carregar estado: %s", e)
        messages = []

    try:
        r = _redis_client()
        meta = _get_meta(r, conversation_id) or {
            "id": conversation_id,
            "title": "Conversa",
            "updated_at": _now_iso(),
            "created_at": _now_iso(),
        }
    except Exception:
        meta = {
            "id": conversation_id,
            "title": "Conversa",
            "updated_at": _now_iso(),
            "created_at": _now_iso(),
        }

    return {
        "session": meta,
        "messages": messages,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Banco Ágil – Agente IA"}


@app.get("/api/debug/logs")
async def get_logs(n: int = Query(default=100, ge=1, le=2000)):
    """Retorna as últimas N linhas do log da aplicação.

    Acesse em desenvolvimento: http://localhost:8000/api/debug/logs
    Útil para diagnóstico sem precisar abrir o terminal do servidor.
    """
    lines = tail_log(n)
    return {
        "total_lines": len(lines),
        "lines": lines,
    }
