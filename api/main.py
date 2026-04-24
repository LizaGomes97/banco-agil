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
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from src.config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from src.graph import get_graph
from src.infrastructure.logging_config import setup_logging, tail_log
from src.infrastructure.metrics import cronometro, metrics
from src.infrastructure.observability_store import (
    STATUS_BLOCKED_INPUT,
    STATUS_COMPLETED,
    STATUS_ERROR,
    observability_store,
)
from src.infrastructure.staging_store import staging_store
from src.middleware.guardrails import Severidade, input_runner, output_runner
from src.tools.intent_classifier import obter_metricas as obter_metricas_classificador

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
    turno_id: Optional[str] = None  # para feedback thumbs up/down (ADR-023)


class CreateConversationRequest(BaseModel):
    title: str = "Nova conversa"


class FeedbackRequest(BaseModel):
    turno_id: str
    feedback: int  # -1 (thumbs down) ou +1 (thumbs up)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Envia uma mensagem para o agente LangGraph e retorna a resposta."""
    graph = get_graph()
    sid = req.conversation_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": sid}}

    logger.info("[CHAT] session=%s | msg=%.80s", sid[:8], req.message)
    metrics.incrementar("chat.requests")
    run_id = observability_store.iniciar_run(session_id=sid)
    _t0 = time.perf_counter()

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
        metrics.incrementar("chat.input_blocked")
        observability_store.finalizar_run(
            run_id,
            status=STATUS_BLOCKED_INPUT,
            duration_ms=int((time.perf_counter() - _t0) * 1000),
        )
        return ChatResponse(
            reply=input_check.mensagem_cliente or "Não consigo processar essa solicitação.",
            conversation_id=sid,
            authenticated=False,
            encerrado=False,
        )

    # ── Verificar se a sessão já foi encerrada ──────────────────────────────
    # Se encerrado=True no estado salvo, bloquear novas mensagens sem reautenticar.
    try:
        estado_atual = graph.get_state(config)
        if estado_atual and estado_atual.values.get("encerrado"):
            logger.info("[CHAT] Sessão %s encerrada — bloqueando nova mensagem", sid[:8])
            return ChatResponse(
                reply=(
                    "Esta sessão foi encerrada. Para continuar, inicie uma nova conversa "
                    "ou forneça seus dados novamente para se identificar."
                ),
                conversation_id=sid,
                authenticated=False,
                encerrado=True,
            )
    except Exception as exc:
        logger.warning("[CHAT] Não foi possível verificar estado da sessão: %s", exc)

    try:
        with cronometro("chat.latency_ms"):
            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=req.message)],
                    # Reset de campos de turno — garantem que o registrar_turno
                    # roda a cada nova mensagem (ver ADR-023).
                    "turno_id": None,
                    "intent_detectada": None,
                    "session_id": sid,
                },
                config=config,
            )
    except Exception as exc:
        metrics.incrementar("chat.errors")
        logger.exception("[CHAT] Erro ao invocar grafo")
        observability_store.finalizar_run(
            run_id,
            status=STATUS_ERROR,
            duration_ms=int((time.perf_counter() - _t0) * 1000),
        )
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
    turno_id_raw = result.get("turno_id")
    turno_id = turno_id_raw if turno_id_raw and turno_id_raw != "skipped" else None
    cliente = result.get("cliente_autenticado") or {}
    observability_store.finalizar_run(
        run_id,
        agent_name=result.get("agente_ativo") or "triagem",
        intent=result.get("intent_detectada"),
        duration_ms=int((time.perf_counter() - _t0) * 1000),
        status=STATUS_COMPLETED,
    )
    if cliente.get("cpf"):
        observability_store.atualizar_cpf_run(run_id, cliente["cpf"])
    logger.info(
        "[CHAT] authenticated=%s encerrado=%s turno=%s reply=%.60s",
        authenticated, encerrado, (turno_id[:8] if turno_id else "-"), reply,
    )
    return ChatResponse(
        reply=reply,
        conversation_id=sid,
        authenticated=authenticated,
        encerrado=encerrado,
        turno_id=turno_id,
    )


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

    authenticated = False
    encerrado = False
    try:
        state = graph.get_state(config)
        if state and state.values:
            messages = _extract_messages(state.values)
            authenticated = bool(state.values.get("cliente_autenticado"))
            encerrado = bool(state.values.get("encerrado"))
        else:
            messages = []
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
        "authenticated": authenticated,
        "encerrado": encerrado,
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


@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Recebe thumbs up/down do frontend para um turno específico (ADR-023).

    O turno_id veio na resposta do /api/chat. O feedback é persistido no
    staging e usado pelo worker de curadoria: turnos com thumbs down NUNCA
    são promovidos à memória vetorial e viram sinal para padrões dinâmicos.
    """
    if req.feedback not in (-1, 1):
        raise HTTPException(
            status_code=400,
            detail="feedback deve ser -1 (thumbs down) ou +1 (thumbs up)",
        )
    try:
        atualizou = await staging_store.registrar_feedback(req.turno_id, req.feedback)
    except Exception:
        logger.exception("Falha ao registrar feedback")
        raise HTTPException(status_code=500, detail="Falha ao registrar feedback")

    if not atualizou:
        raise HTTPException(status_code=404, detail="turno_id não encontrado")

    metrics.incrementar(f"feedback.{'up' if req.feedback > 0 else 'down'}")
    logger.info("[FEEDBACK] turno=%s feedback=%d", req.turno_id[:8], req.feedback)
    return {"ok": True, "turno_id": req.turno_id, "feedback": req.feedback}


@app.get("/api/debug/curator")
async def curator_list(
    limit: int = Query(default=50, ge=1, le=500),
    intent: Optional[str] = Query(default=None),
    feedback: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """Lista turnos do staging para dashboard de curadoria humana (ADR-023).

    Filtros:
      - intent: credito | cambio | encerrar | nenhum
      - feedback: -1 (thumbs down) | 1 (thumbs up)
      - status: pending | approved | rejected | grouped
    """
    try:
        turnos = await staging_store.listar_recentes(
            limit=limit, intent=intent, feedback=feedback, status=status,
        )
        return {"count": len(turnos), "turnos": turnos}
    except Exception:
        logger.exception("Falha ao listar turnos do staging")
        return {"count": 0, "turnos": []}


@app.get("/api/debug/curator/audit")
async def curator_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    action: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    batch: Optional[int] = Query(default=None),
):
    """Trilha de auditoria do curador — uma linha por decisão tomada.

    Filtros:
      - action: APPROVE | REJECT | GROUP | AUTO_REJECT_THUMBS_DOWN | PRO_OVERRIDE
      - source: flash | pro | auto
      - batch:  número do batch (inteiro)

    Retorna contagem agregada + lista de decisões com contexto do turno.
    """
    try:
        decisoes = await staging_store.listar_decisoes(
            limit=limit, action=action, source=source, batch_number=batch,
        )
        resumo = await staging_store.contar_decisoes_por_action()
        return {"count": len(decisoes), "resumo": resumo, "decisoes": decisoes}
    except Exception:
        logger.exception("Falha ao listar decisões do curador")
        return {"count": 0, "resumo": {}, "decisoes": []}


@app.get("/api/debug/curator/vectors")
async def curator_vectors(
    collection: str = Query(
        default="routing",
        pattern="^(routing|templates)$",
    ),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Lista o que está indexado no Qdrant para auditoria manual.

    Aliases para as collections reais (ADR-023 — únicas coleções ativas):
      - routing   → banco_agil_learned_routing   (intents + exemplos)
      - templates → banco_agil_learned_templates (esqueletos de resposta)
    """
    from src.infrastructure.vector_store import (
        COLLECTION_LEARNED_ROUTING,
        COLLECTION_LEARNED_TEMPLATES,
        vector_store,
    )

    mapa = {
        "routing": COLLECTION_LEARNED_ROUTING,
        "templates": COLLECTION_LEARNED_TEMPLATES,
    }
    col_real = mapa[collection]
    try:
        total = await vector_store.count(col_real)
        pontos = await vector_store.listar_pontos(col_real, limit=limit)
        return {
            "collection": col_real,
            "alias": collection,
            "total": total,
            "count": len(pontos),
            "pontos": pontos,
        }
    except Exception:
        logger.exception("Falha ao listar pontos do Qdrant (%s)", col_real)
        return {
            "collection": col_real, "alias": collection,
            "total": 0, "count": 0, "pontos": [],
        }


@app.get("/api/debug/curator/golden")
async def curator_golden(
    agente: str | None = Query(default=None, pattern="^(triagem|cambio|credito|entrevista)$"),
):
    """Visão agregada da memória Golden (ADR-023).

    Retorna:
      - counts: total de pontos em cada collection, agrupados por source
                (golden/worker) para ver o quanto o sistema aprendeu vs curado manualmente.
      - licoes: lições ativas em SQLite, filtráveis por agente, ordenadas golden-first.
      - metricas_classificador: shortcut/fewshot hits do intent_classifier
                                 (indica quanto a golden está sendo usada em runtime).
    """
    from src.infrastructure.learned_memory import obter_regras_ativas_sync
    from src.infrastructure.vector_store import (
        COLLECTION_LEARNED_ROUTING,
        COLLECTION_LEARNED_TEMPLATES,
        SOURCE_GOLDEN,
        SOURCE_WORKER,
        vector_store,
    )

    async def _contar_por_source(col: str) -> dict[str, int]:
        try:
            total = await vector_store.count(col)
        except Exception:
            total = 0
        por_source: dict[str, int] = {SOURCE_GOLDEN: 0, SOURCE_WORKER: 0, "outro": 0}
        try:
            pontos = await vector_store.listar_pontos(col, limit=500)
            for p in pontos:
                src = (p.get("metadata") or {}).get("source") or "outro"
                por_source[src] = por_source.get(src, 0) + 1
        except Exception:
            logger.exception("Falha ao contar por source em %s", col)
        return {"total": total, **por_source}

    counts = {
        "routing": await _contar_por_source(COLLECTION_LEARNED_ROUTING),
        "templates": await _contar_por_source(COLLECTION_LEARNED_TEMPLATES),
    }

    licoes = obter_regras_ativas_sync(agente=agente) or []

    try:
        from src.tools.intent_classifier import obter_metricas
        intent_metrics = obter_metricas() or {}
    except Exception:
        intent_metrics = {}

    return {
        "counts": counts,
        "licoes": licoes,
        "agente_filtro": agente,
        "metricas_classificador": intent_metrics,
    }


@app.get("/api/debug/runs")
async def debug_runs(limit: int = Query(default=50, ge=1, le=500)):
    """Últimos N runs do agente (observabilidade)."""
    return {"runs": observability_store.listar_runs(limit=limit)}


_CURATOR_DASHBOARD_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>Banco &Aacute;gil — Dashboard do Curador</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         margin: 0; padding: 24px; background: #0b1020; color: #e6e9f2; }
  h1 { margin: 0 0 8px; font-size: 22px; }
  .sub { color: #8b93a8; margin-bottom: 20px; font-size: 12px; }
  .tabs { display:flex; gap:4px; margin-bottom: 18px; border-bottom:1px solid #2a3160; }
  .tab { padding: 10px 18px; cursor:pointer; color:#8b93a8; border:1px solid transparent;
         border-bottom:none; border-radius:8px 8px 0 0; font-weight:500; user-select:none; }
  .tab:hover { color:#e6e9f2; }
  .tab.active { background:#121833; color:#e6e9f2; border-color:#2a3160; }
  .panel { display:none; }
  .panel.active { display:block; }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; align-items:center; }
  .filters label { font-size: 12px; color: #8b93a8; }
  .filters select, .filters input, .filters button {
    background: #121833; color: #e6e9f2; border: 1px solid #2a3160;
    padding: 6px 10px; border-radius: 6px; font-size: 13px;
  }
  .filters button { cursor: pointer; background: #3b82f6; border: none; }
  .filters button:hover { background: #2563eb; }
  table { width: 100%; border-collapse: collapse; background: #121833;
          border-radius: 8px; overflow: hidden; }
  th, td { padding: 10px 12px; text-align: left; vertical-align: top;
           border-bottom: 1px solid #1f2547; font-size: 13px; }
  th { background: #1a2048; color: #b6c0df; font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: .04em; }
  tr:hover td { background: #161c3b; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; font-weight: 500; }
  .pill.credito  { background: #3b2a58; color: #d4b8ff; }
  .pill.cambio   { background: #1e3a5f; color: #9ec8ff; }
  .pill.encerrar { background: #3a3a3a; color: #c8c8c8; }
  .pill.nenhum   { background: #4a2a2a; color: #ffb8b8; }
  .pill.pending  { background: #4a3a00; color: #ffd780; }
  .pill.approved { background: #1a4a2a; color: #9effb8; }
  .pill.rejected { background: #4a1a1a; color: #ff9e9e; }
  .pill.APPROVE { background: #1a4a2a; color: #9effb8; }
  .pill.REJECT  { background: #4a1a1a; color: #ff9e9e; }
  .pill.GROUP   { background: #3a3a3a; color: #c8c8c8; }
  .pill.AUTO_REJECT_THUMBS_DOWN { background:#4a1a2a; color:#ffb8c8; }
  .pill.PRO_OVERRIDE { background:#3b2a58; color:#d4b8ff; }
  .pill.flash { background:#1e3a5f; color:#9ec8ff; }
  .pill.pro { background:#3b2a58; color:#d4b8ff; }
  .pill.auto { background:#4a3a00; color:#ffd780; }
  .pill.golden { background:#4a3a00; color:#ffd780; }
  .pill.worker { background:#1e3a5f; color:#9ec8ff; }
  .pill.outro { background:#3a3a3a; color:#c8c8c8; }
  .pill.triagem { background:#1e3a5f; color:#9ec8ff; }
  .pill.entrevista { background:#2a3a1e; color:#c8ff9e; }
  h3 { margin: 16px 0 8px; }
  .fb-up   { color: #86efac; }
  .fb-down { color: #fca5a5; }
  .msg { max-width: 320px; color: #c8d0e8; }
  .msg.user { color: #9ec8ff; }
  .meta { color: #8b93a8; font-size: 11px; }
  .empty { padding: 40px; text-align: center; color: #8b93a8; }
  .stats { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat { background: #121833; padding: 12px 16px; border-radius: 8px;
          border: 1px solid #2a3160; flex: 1; min-width: 140px; }
  .stat .k { font-size: 11px; color: #8b93a8; text-transform: uppercase; }
  .stat .v { font-size: 22px; font-weight: 600; margin-top: 4px; }
  a { color: #93c5fd; }
  code { background:#0f1530; padding:1px 5px; border-radius:4px; font-size:12px; }
</style>
</head>
<body>
  <h1>Dashboard do Curador</h1>
  <div class="sub">
    Somente leitura &middot;
    <a href="/docs">Swagger</a> &middot;
    <a href="/api/debug/metrics">m&eacute;tricas</a> &middot;
    <a href="/api/debug/runs">runs</a> &middot;
    Log do worker em <code>data/curator.log</code>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="golden">Mem&oacute;ria Golden</div>
    <div class="tab" data-tab="staging">Staging</div>
    <div class="tab" data-tab="audit">Decis&otilde;es do curador</div>
    <div class="tab" data-tab="vectors">Qdrant (coleções)</div>
  </div>

  <!-- ════════ ABA GOLDEN (ADR-023) ════════ -->
  <div class="panel active" id="p-golden">
    <div class="sub" style="margin-bottom:12px">
      Mem&oacute;ria aprendida do sistema (ADR-023). Padr&otilde;es <span class="pill golden">golden</span>
      s&atilde;o curados manualmente via <code>seeds/patterns.json</code>;
      <span class="pill worker">worker</span> s&atilde;o aprendidos automaticamente pelo curador a partir de
      discrep&acirc;ncias Flash vs Pro.
    </div>
    <div class="stats" id="golden-stats"></div>
    <div class="filters">
      <label>Agente:
        <select id="f-licoes-agente">
          <option value="">(todos)</option>
          <option value="triagem">triagem</option>
          <option value="cambio">cambio</option>
          <option value="credito">credito</option>
          <option value="entrevista">entrevista</option>
        </select>
      </label>
      <button onclick="carregarGolden()">Atualizar</button>
    </div>
    <h3 style="margin-top:24px;color:#b6c0df;font-size:13px;text-transform:uppercase;letter-spacing:.04em">
      Li&ccedil;&otilde;es ativas
    </h3>
    <table>
      <thead><tr>
        <th>Origem</th><th>Regra</th><th>Motivo</th><th>Aplic&aacute;vel a</th>
      </tr></thead>
      <tbody id="tbody-licoes"></tbody>
    </table>
    <h3 style="margin-top:24px;color:#b6c0df;font-size:13px;text-transform:uppercase;letter-spacing:.04em">
      Uso em runtime (intent classifier)
    </h3>
    <div class="stats" id="golden-classifier"></div>
  </div>

  <!-- ════════ ABA STAGING ════════ -->
  <div class="panel" id="p-staging">
    <div class="stats">
      <div class="stat"><div class="k">Total exibido</div><div class="v" id="s-total">&mdash;</div></div>
      <div class="stat"><div class="k">Pendentes</div><div class="v" id="s-pending">&mdash;</div></div>
      <div class="stat"><div class="k">&#128077; Thumbs up</div><div class="v fb-up" id="s-up">&mdash;</div></div>
      <div class="stat"><div class="k">&#128078; Thumbs down</div><div class="v fb-down" id="s-down">&mdash;</div></div>
    </div>
    <div class="filters">
      <label>Intent:
        <select id="f-intent">
          <option value="">(todas)</option>
          <option value="credito">credito</option>
          <option value="cambio">cambio</option>
          <option value="encerrar">encerrar</option>
          <option value="nenhum">nenhum</option>
        </select>
      </label>
      <label>Feedback:
        <select id="f-feedback">
          <option value="">(todos)</option>
          <option value="1">&#128077; Up</option>
          <option value="-1">&#128078; Down</option>
        </select>
      </label>
      <label>Status:
        <select id="f-status">
          <option value="">(todos)</option>
          <option value="pending">pending</option>
          <option value="approved">approved</option>
          <option value="rejected">rejected</option>
        </select>
      </label>
      <label>Limit:
        <input id="f-limit" type="number" min="1" max="500" value="50" />
      </label>
      <button onclick="carregarStaging()">Filtrar</button>
      <button onclick="resetStaging()">Reset</button>
    </div>
    <table>
      <thead><tr>
        <th>Hora</th><th>CPF</th><th>Intent</th>
        <th>Mensagem</th><th>Resposta</th>
        <th>FB</th><th>Status</th>
      </tr></thead>
      <tbody id="tbody-staging"></tbody>
    </table>
  </div>

  <!-- ════════ ABA DECISÕES ════════ -->
  <div class="panel" id="p-audit">
    <div class="stats" id="audit-stats"></div>
    <div class="filters">
      <label>Action:
        <select id="f-action">
          <option value="">(todas)</option>
          <option value="APPROVE">APPROVE</option>
          <option value="REJECT">REJECT</option>
          <option value="GROUP">GROUP</option>
          <option value="AUTO_REJECT_THUMBS_DOWN">AUTO_REJECT_THUMBS_DOWN</option>
          <option value="PRO_OVERRIDE">PRO_OVERRIDE</option>
        </select>
      </label>
      <label>Origem:
        <select id="f-source">
          <option value="">(todas)</option>
          <option value="flash">flash</option>
          <option value="pro">pro</option>
          <option value="auto">auto</option>
        </select>
      </label>
      <label>Batch:
        <input id="f-batch" type="number" min="1" placeholder="(todos)" style="width:100px" />
      </label>
      <label>Limit:
        <input id="f-limit-a" type="number" min="1" max="1000" value="100" />
      </label>
      <button onclick="carregarAudit()">Filtrar</button>
      <button onclick="resetAudit()">Reset</button>
    </div>
    <table>
      <thead><tr>
        <th>Hora</th><th>Batch</th><th>Action</th><th>Origem</th>
        <th>Motivo</th><th>Intent</th><th>Turno (user / agent)</th>
        <th>Qdrant</th>
      </tr></thead>
      <tbody id="tbody-audit"></tbody>
    </table>
  </div>

  <!-- ════════ ABA QDRANT ════════ -->
  <div class="panel" id="p-vectors">
    <div class="filters">
      <label>Collection:
        <select id="f-collection">
          <option value="routing">learned_routing (golden + worker)</option>
          <option value="templates">learned_templates (golden + worker)</option>
        </select>
      </label>
      <label>Limit:
        <input id="f-limit-v" type="number" min="1" max="500" value="50" />
      </label>
      <button onclick="carregarVectors()">Carregar</button>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">Total na collection</div><div class="v" id="v-total">&mdash;</div></div>
      <div class="stat"><div class="k">Exibidos agora</div><div class="v" id="v-count">&mdash;</div></div>
      <div class="stat"><div class="k">Collection real</div><div class="v" style="font-size:14px" id="v-name">&mdash;</div></div>
    </div>
    <table>
      <thead><tr>
        <th>doc_id</th><th>Intent</th><th>Agente</th>
        <th>Conte&uacute;do indexado</th><th>Metadata extra</th>
      </tr></thead>
      <tbody id="tbody-vectors"></tbody>
    </table>
  </div>

<script>
function esc(s){ return (s==null?"":String(s)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function pill(cls, text){ return `<span class="pill ${cls}">${esc(text)}</span>`; }
function fbEmoji(v){ if(v===1) return '<span class="fb-up">&#128077;</span>';
                     if(v===-1) return '<span class="fb-down">&#128078;</span>';
                     return '<span class="meta">&mdash;</span>'; }
function truncate(s, n){ s=String(s||""); return s.length>n ? s.slice(0,n)+"…" : s; }

document.querySelectorAll('.tab').forEach(t=>{
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    const id = 'p-'+t.dataset.tab;
    document.getElementById(id).classList.add('active');
    if(t.dataset.tab === 'golden')  carregarGolden();
    if(t.dataset.tab === 'staging') carregarStaging();
    if(t.dataset.tab === 'audit')   carregarAudit();
    if(t.dataset.tab === 'vectors') carregarVectors();
  });
});

async function carregarGolden(){
  const ag = document.getElementById('f-licoes-agente').value;
  const url = '/api/debug/curator/golden' + (ag ? ('?agente=' + encodeURIComponent(ag)) : '');
  const r = await fetch(url);
  const data = await r.json();
  const counts = data.counts || {};
  const stats = document.getElementById('golden-stats');
  stats.innerHTML = '';
  for (const [nome, info] of Object.entries(counts)) {
    const golden = info.golden || 0;
    const worker = info.worker || 0;
    const total = info.total || 0;
    stats.innerHTML += `
      <div class="stat">
        <div class="k">${esc(nome)}</div>
        <div class="v">${total}</div>
        <div class="meta">
          ${pill('golden','golden')} ${golden}
          &middot;
          ${pill('worker','worker')} ${worker}
        </div>
      </div>`;
  }

  const tbody = document.getElementById('tbody-licoes');
  tbody.innerHTML = '';
  const licoes = data.licoes || [];
  for (const l of licoes) {
    const aplicaveis = Array.isArray(l.aplicavel_a) ? l.aplicavel_a : [];
    const pills = aplicaveis.length
      ? aplicaveis.map(a => pill(a, a)).join(' ')
      : '<span class="meta">(todos)</span>';
    const src = l.source || 'outro';
    tbody.innerHTML += `
      <tr>
        <td>${pill(src, src)}</td>
        <td class="msg">${esc(l.regra || l.example_text || '')}</td>
        <td class="meta">${esc(l.motivo || '')}</td>
        <td>${pills}</td>
      </tr>`;
  }
  if (!licoes.length) {
    const filtro = data.agente_filtro ? ` para o agente ${esc(data.agente_filtro)}` : '';
    tbody.innerHTML = `<tr><td colspan="4" class="empty">Nenhuma li&ccedil;&atilde;o ativa${filtro}. Rode <code>python scripts/seed_patterns.py</code> para popular golden.</td></tr>`;
  }

  const cls = document.getElementById('golden-classifier');
  const m = data.metricas_classificador || {};
  const total = m.total || 0;
  const shortcut = m.golden_shortcut || 0;
  const fewshot = m.golden_fewshot_hit || 0;
  const llmOk = m.llm_ok || 0;
  const pctShortcut = total ? Math.round(100*shortcut/total) : 0;
  const pctFewshot = total ? Math.round(100*fewshot/total) : 0;
  cls.innerHTML = `
    <div class="stat"><div class="k">Classifica&ccedil;&otilde;es totais</div><div class="v">${total}</div></div>
    <div class="stat"><div class="k">Shortcut golden (sem LLM)</div>
      <div class="v">${shortcut}</div>
      <div class="meta">${pctShortcut}% do total</div></div>
    <div class="stat"><div class="k">Few-shot injetado no LLM</div>
      <div class="v">${fewshot}</div>
      <div class="meta">${pctFewshot}% do total</div></div>
    <div class="stat"><div class="k">LLM ok</div><div class="v">${llmOk}</div></div>`;
}

async function carregarStaging(){
  const params = new URLSearchParams();
  const int = document.getElementById('f-intent').value;
  const fb  = document.getElementById('f-feedback').value;
  const st  = document.getElementById('f-status').value;
  const lim = document.getElementById('f-limit').value || 50;
  if (int) params.set('intent', int);
  if (fb)  params.set('feedback', fb);
  if (st)  params.set('status', st);
  params.set('limit', lim);
  const r = await fetch('/api/debug/curator?' + params.toString());
  const data = await r.json();
  const rows = data.turnos || [];
  const tbody = document.getElementById('tbody-staging');
  tbody.innerHTML = '';
  let up=0, down=0, pending=0;
  for (const t of rows) {
    if (t.user_feedback === 1) up++;
    if (t.user_feedback === -1) down++;
    if (t.status === 'pending') pending++;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="meta">${esc(t.created_at || '')}</td>
      <td class="meta">${esc(t.cpf || '')}</td>
      <td>${t.intent ? pill(t.intent, t.intent) : ''}</td>
      <td class="msg user">${esc(truncate(t.user_message, 140))}</td>
      <td class="msg">${esc(truncate(t.agent_response, 180))}</td>
      <td>${fbEmoji(t.user_feedback)}</td>
      <td>${pill(t.status||'pending', t.status||'pending')}</td>`;
    tbody.appendChild(tr);
  }
  document.getElementById('s-total').textContent = rows.length;
  document.getElementById('s-pending').textContent = pending;
  document.getElementById('s-up').textContent = up;
  document.getElementById('s-down').textContent = down;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Nenhum turno no staging. Converse com o agente para popular.</td></tr>';
  }
}
function resetStaging(){
  document.getElementById('f-intent').value='';
  document.getElementById('f-feedback').value='';
  document.getElementById('f-status').value='';
  document.getElementById('f-limit').value='50';
  carregarStaging();
}

async function carregarAudit(){
  const params = new URLSearchParams();
  const ac = document.getElementById('f-action').value;
  const so = document.getElementById('f-source').value;
  const bt = document.getElementById('f-batch').value;
  const lim = document.getElementById('f-limit-a').value || 100;
  if (ac) params.set('action', ac);
  if (so) params.set('source', so);
  if (bt) params.set('batch', bt);
  params.set('limit', lim);
  const r = await fetch('/api/debug/curator/audit?' + params.toString());
  const data = await r.json();
  const rows = data.decisoes || [];
  const resumo = data.resumo || {};
  const statsHost = document.getElementById('audit-stats');
  statsHost.innerHTML = '';
  for (const [k,v] of Object.entries(resumo)) {
    statsHost.innerHTML += `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`;
  }
  if (!Object.keys(resumo).length) {
    statsHost.innerHTML = '<div class="stat"><div class="k">Decis&otilde;es registradas</div><div class="v">0</div></div>';
  }
  const tbody = document.getElementById('tbody-audit');
  tbody.innerHTML = '';
  for (const d of rows) {
    const qd = d.vector_collection ? `<code>${esc(d.vector_collection)}</code>` : '<span class="meta">&mdash;</span>';
    const turno = `<div class="msg user">${esc(truncate(d.user_message, 100))}</div>
                   <div class="msg">${esc(truncate(d.agent_response, 140))}</div>`;
    tbody.innerHTML += `
      <tr>
        <td class="meta">${esc(d.decided_at || '')}</td>
        <td class="meta">#${esc(d.batch_number || '-')}</td>
        <td>${pill(d.action || '', d.action || '-')}</td>
        <td>${pill(d.source || '', d.source || '-')}</td>
        <td class="msg">${esc(truncate(d.reason, 180))}</td>
        <td>${d.intent ? pill(d.intent, d.intent) : ''}</td>
        <td>${turno}</td>
        <td>${qd}</td>
      </tr>`;
  }
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">Nenhuma decis&atilde;o registrada ainda. Rode <code>python -m src.worker.curator --once</code>.</td></tr>';
  }
}
function resetAudit(){
  document.getElementById('f-action').value='';
  document.getElementById('f-source').value='';
  document.getElementById('f-batch').value='';
  document.getElementById('f-limit-a').value='100';
  carregarAudit();
}

async function carregarVectors(){
  const col = document.getElementById('f-collection').value;
  const lim = document.getElementById('f-limit-v').value || 50;
  const r = await fetch('/api/debug/curator/vectors?collection='+encodeURIComponent(col)+'&limit='+lim);
  const data = await r.json();
  document.getElementById('v-total').textContent = data.total ?? 0;
  document.getElementById('v-count').textContent = data.count ?? 0;
  document.getElementById('v-name').textContent = data.collection || '';
  const tbody = document.getElementById('tbody-vectors');
  tbody.innerHTML = '';
  for (const p of (data.pontos || [])) {
    const md = p.metadata || {};
    const intent = md.intent || '';
    const agent = md.agent_name || '';
    const extras = Object.entries(md).filter(([k])=>!['intent','agent_name','cpf','curated_from','rejected_from'].includes(k));
    const extrasStr = extras.map(([k,v])=>`<code>${esc(k)}=${esc(String(v))}</code>`).join(' ');
    tbody.innerHTML += `
      <tr>
        <td class="meta">${esc(truncate(p.doc_id, 36))}</td>
        <td>${intent ? pill(intent, intent) : ''}</td>
        <td>${esc(agent)}</td>
        <td class="msg">${esc(truncate(p.text, 260))}</td>
        <td class="meta">${extrasStr}</td>
      </tr>`;
  }
  if (!(data.pontos || []).length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">Collection vazia. Aprove turnos no worker para popular.</td></tr>';
  }
}

carregarGolden();
setInterval(() => {
  const ativa = document.querySelector('.tab.active').dataset.tab;
  if (ativa === 'golden') carregarGolden();
  else if (ativa === 'staging') carregarStaging();
  else if (ativa === 'audit') carregarAudit();
}, 10000);
</script>
</body>
</html>
"""


@app.get("/api/debug/curator/dashboard", response_class=HTMLResponse)
async def curator_dashboard():
    """Dashboard HTML simples para revisão humana dos turnos em staging.

    Lê o endpoint JSON /api/debug/curator. Não requer SPA separada.
    Auto-refresh a cada 10s. Somente leitura (ver ADR-023).
    """
    return HTMLResponse(content=_CURATOR_DASHBOARD_HTML)


@app.get("/api/debug/metrics")
async def get_metrics():
    """Métricas operacionais em memória.

    Inclui contadores (requests, erros, feedback), latência p50/p95/p99
    do grafo, e estatísticas do classificador de intenções
    (quantas passaram pelo LLM vs heurística vs fallback final).

    Zeradas a cada restart — é diagnóstico, não telemetria persistente.
    Para séries históricas, ver tabelas `agent_runs` e `memory_staging`.
    """
    return {
        "api": metrics.snapshot(),
        "classificador_intencao": obter_metricas_classificador(),
    }
