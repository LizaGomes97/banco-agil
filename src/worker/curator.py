"""Worker Curador — processo independente de curadoria da memória aprendida.

Roda separado do FastAPI, lendo `memory_staging` e produzindo candidatos de
padrões (roteamento, templates, lições) para as collections `banco_agil_learned_*`
no Qdrant e para `curator_lessons` no SQLite. Ver ADR-023.

Estratégia de aprendizado (resumo):
  - Discrepâncias entre Flash e Pro viram candidatos de lição.
  - Turnos com thumbs-down geram padrões negativos destilados.
  - Taxa de aprovação recente ajusta o tom do prompt do curador.

Uso:
    python -m src.worker.curator --once              # 1 batch e sai
    python -m src.worker.curator                      # contínuo, poll 30s
    python -m src.worker.curator --interval 60       # poll 60s
    python -m src.worker.curator --batch-size 10     # batches de 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY_CURATOR, GEMINI_MODEL, ROOT_DIR
from src.infrastructure.staging_store import (
    ACTION_APPROVE,
    ACTION_AUTO_THUMBS_DOWN,
    ACTION_GROUP,
    ACTION_PRO_OVERRIDE,
    ACTION_REJECT,
    LESSON_FLASH_APROVOU_PRO_REJEITOU,
    LESSON_FLASH_REJEITOU_PRO_APROVOU,
    LESSON_SOURCE_WORKER,
    SOURCE_AUTO,
    SOURCE_FLASH,
    SOURCE_PRO,
    STATUS_APPROVED,
    STATUS_REJECTED,
    staging_store,
)
# NB: VectorStore é intencionalmente não importado aqui. Após ADR-023 o worker
# não escreve mais em coleções vetoriais — apenas destila lições em SQLite via
# `registrar_licoes`. Se precisar voltar a indexar, importar vector_store
# e as coleções desejadas apenas de `learned_routing` / `learned_templates`.

_LOG_PATH = ROOT_DIR / "data" / "curator.log"

logger = logging.getLogger("curador")

# Modelos dedicados ao curador. Chave separada evita competir com chat.
_FLASH_MODEL = "gemini-2.5-flash"
_PRO_MODEL = "gemini-2.5-pro"

# Cadência: a cada PRO_AUDIT_EVERY batches, o Pro audita uma amostra
# do que o Flash classificou — discrepâncias viram lições (Camada 1).
PRO_AUDIT_EVERY = 3
PRO_AUDIT_SAMPLE_SIZE = 3


# ── Prompt dinâmico com 3 camadas ─────────────────────────────────────────

_BASE_PROMPT = """\
Você é um curador de memória de um assistente bancário (Banco Ágil).
Sua tarefa: decidir QUAIS turnos merecem virar memória permanente para
reuso futuro por agentes de crédito e câmbio.

Classifique cada turno em UMA das opções:
  APPROVE  — turno bom, útil como referência futura (decisão clara, tom adequado, sem alucinação)
  REJECT   — turno ruim (resposta genérica, erro, tom inadequado, alucinação) OU com thumbs down
  GROUP    — turno apenas parcial (pergunta de coleta sem decisão) que deveria ser agrupado com próximos

Critérios de aprovação:
  - Resposta referencia dados reais do cliente (sem alucinação)
  - Decisão ou informação é acionável (não é só "como posso ajudar?")
  - Tom profissional, claro, em português
  - NUNCA aprovar turnos com user_feedback = -1 (thumbs down do usuário)

Responda em JSON array, um item por turno:
[{"id": "<id>", "action": "APPROVE|REJECT|GROUP", "reason": "<5-10 palavras>"}]
"""


async def _construir_prompt_dinamico() -> str:
    """Monta o system prompt injetando lições, padrões e calibração."""
    partes = [_BASE_PROMPT]

    # Camada 1 — Lições
    licoes = await staging_store.obter_licoes(per_direction=3)
    exemplos_rejeicao = licoes.get(LESSON_FLASH_APROVOU_PRO_REJEITOU, [])
    exemplos_aprovacao = licoes.get(LESSON_FLASH_REJEITOU_PRO_APROVOU, [])
    if exemplos_rejeicao:
        partes.append(
            "\n## Lições — turnos que você tende a APROVAR mas deveria REJEITAR:\n"
            + "\n".join(f"- {ex}" for ex in exemplos_rejeicao)
        )
    if exemplos_aprovacao:
        partes.append(
            "\n## Lições — turnos que você tende a REJEITAR mas são VÁLIDOS:\n"
            + "\n".join(f"- {ex}" for ex in exemplos_aprovacao)
        )

    # Camada 2 — Padrões dinâmicos (topo por hit_count)
    padroes = await staging_store.obter_padroes(limit=5)
    if padroes:
        partes.append(
            "\n## Padrões problemáticos frequentes (REJEITE se aparecerem):\n"
            + "\n".join(f"- {p}" for p in padroes)
        )

    # Camada 3 — Auto-calibração
    taxa = await staging_store.obter_taxa_aprovacao(last_n=10)
    if taxa is not None:
        if taxa > 0.9:
            partes.append(
                "\n## Calibração: taxa de aprovação recente está ALTA ({:.0%}). "
                "Seja MAIS criterioso nesta rodada — só aprove o que for claramente excelente."
                .format(taxa)
            )
        elif taxa < 0.25:
            partes.append(
                "\n## Calibração: taxa de aprovação recente está BAIXA ({:.0%}). "
                "Seja MAIS permissivo — vários turnos válidos estão sendo rejeitados."
                .format(taxa)
            )
    return "\n".join(partes)


# ── Flash classificador ───────────────────────────────────────────────────

def _flash_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=_FLASH_MODEL,
        temperature=0,
        google_api_key=GEMINI_API_KEY_CURATOR,
        max_output_tokens=1024,
    )


def _pro_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=_PRO_MODEL,
        temperature=0,
        google_api_key=GEMINI_API_KEY_CURATOR,
        max_output_tokens=2048,
    )


def _resumo_turno(t: dict) -> str:
    fb = t.get("user_feedback")
    fb_str = (
        " [USER FEEDBACK: -1 THUMBS DOWN]" if fb == -1
        else " [USER FEEDBACK: +1 THUMBS UP]" if fb == 1 else ""
    )
    return (
        f"id={t['id']} intent={t.get('intent')} agent={t.get('agent_name')}{fb_str}\n"
        f"USER: {t.get('user_message', '')[:300]}\n"
        f"AGENT: {t.get('agent_response', '')[:500]}\n"
    )


def _parse_json_array(content: str) -> list[dict]:
    txt = (content or "").strip()
    if "```" in txt:
        txt = txt.split("```")[1]
        if txt.lstrip().lower().startswith("json"):
            txt = txt.split("\n", 1)[1] if "\n" in txt else txt[4:]
    txt = txt.strip()
    start = txt.find("[")
    end = txt.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        return json.loads(txt[start : end + 1])
    except json.JSONDecodeError:
        logger.exception("Falha ao parsear JSON do classificador")
        return []


async def classificar_batch_flash(turnos: list[dict]) -> list[dict]:
    """Pede ao Flash pra classificar todo o batch. Retorna lista de decisões."""
    prompt = await _construir_prompt_dinamico()
    body = "\n\n".join(f"## TURNO {i+1}\n{_resumo_turno(t)}" for i, t in enumerate(turnos))
    mensagens = [
        SystemMessage(content=prompt),
        HumanMessage(
            content=(
                f"Classifique {len(turnos)} turnos abaixo. "
                "Responda SOMENTE com o JSON array.\n\n" + body
            )
        ),
    ]
    resposta = await asyncio.to_thread(_flash_llm().invoke, mensagens)
    decisoes = _parse_json_array(getattr(resposta, "content", "") or "")
    return decisoes


# ── Pro auditor (Camada 1) ────────────────────────────────────────────────

async def pro_auditar(
    turnos: list[dict],
    decisoes_flash: list[dict],
) -> list[dict]:
    """Pro audita uma amostra. Retorna lista de discrepâncias."""
    if not turnos or not decisoes_flash:
        return []
    n = min(PRO_AUDIT_SAMPLE_SIZE, len(turnos))
    amostra = random.sample(list(zip(turnos, decisoes_flash)), n)
    discrepancias = []

    prompt_pro = (
        "Você é um AUDITOR sênior. Revise a decisão do curador júnior (Flash) "
        "sobre estes turnos. Para cada um, diga se a ação foi correta (AGREE) "
        "ou errada (DISAGREE) e justifique em uma linha.\n"
        'Responda em JSON array: [{"id":"...","verdict":"AGREE|DISAGREE","justificativa":"..."}]'
    )
    body = "\n\n".join(
        f"## TURNO\n{_resumo_turno(t)}\n## DECISÃO FLASH: {d.get('action')} — {d.get('reason','')}"
        for t, d in amostra
    )
    mensagens = [SystemMessage(content=prompt_pro), HumanMessage(content=body)]
    resposta = await asyncio.to_thread(_pro_llm().invoke, mensagens)
    veredictos = _parse_json_array(getattr(resposta, "content", "") or "")

    for (turno, decisao_flash), veredicto in zip(amostra, veredictos):
        if veredicto.get("verdict", "").upper() == "DISAGREE":
            discrepancias.append({
                "turno": turno,
                "decisao_flash": decisao_flash,
                "justificativa": veredicto.get("justificativa", ""),
            })
    return discrepancias


_PROMPT_DESTILAR_LICAO = """\
Você destila lições para prompts de agentes bancários do Banco Ágil.

Dado o turno abaixo e a justificativa do auditor (Pro), gere UMA regra acionável
em 1-2 frases que, injetada no system prompt do agente correspondente, evitaria
esse tipo de erro em futuros atendimentos.

Requisitos DURAS:
- A regra deve ser GERAL, não citar dados deste cliente específico.
- SEM PII (nome, CPF, e-mail, data de nascimento, telefone, endereço, valores específicos).
- Tom imperativo ("Nunca...", "Sempre que...", "Se X, então Y").
- NO MÁXIMO 200 caracteres.
- `aplicavel_a` deve ser uma lista de agentes dentre: triagem, cambio, credito, entrevista.
- `motivo` é uma frase curta explicando POR QUE a regra existe (para humanos auditarem depois).

Responda APENAS um JSON válido, sem markdown, no formato:
{"regra": "...", "motivo": "...", "aplicavel_a": ["..."]}
"""


async def _destilar_licao_pro(discrepancia: dict) -> dict | None:
    """Usa o Flash para destilar a discrepância em uma regra estruturada.

    Retorna dict {regra, motivo, aplicavel_a} ou None se falhar / vier inválido.
    """
    turno = discrepancia["turno"]
    decisao_flash = discrepancia["decisao_flash"]
    justificativa_pro = (discrepancia.get("justificativa") or "")[:400]
    agente = (turno.get("agent_name") or "").lower() or "triagem"
    intent = turno.get("intent") or ""

    body = (
        f"## Contexto\n"
        f"Agente: {agente}\n"
        f"Intent: {intent}\n"
        f"Flash decidiu: {decisao_flash.get('action','')} — {decisao_flash.get('reason','')}\n"
        f"Pro DISCORDOU. Motivo: {justificativa_pro}\n\n"
        f"## Turno\n"
        f"USER: {(turno.get('user_message') or '')[:300]}\n"
        f"AGENT: {(turno.get('agent_response') or '')[:400]}\n"
    )
    mensagens = [
        SystemMessage(content=_PROMPT_DESTILAR_LICAO),
        HumanMessage(content=body),
    ]
    try:
        resposta = await asyncio.to_thread(_flash_llm().invoke, mensagens)
        raw = (getattr(resposta, "content", "") or "").strip()
        # Remove cercas de markdown se vierem por descuido do modelo
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
    except Exception:
        logger.exception("Falha ao destilar lição do Pro")
        return None

    regra = (data.get("regra") or "").strip()
    motivo = (data.get("motivo") or "").strip()
    aplicavel_a = data.get("aplicavel_a") or [agente]
    if not isinstance(aplicavel_a, list):
        aplicavel_a = [agente]
    aplicavel_a = [str(a).lower() for a in aplicavel_a if a]
    if not regra or len(regra) > 280:
        return None

    return {"regra": regra, "motivo": motivo, "aplicavel_a": aplicavel_a}


async def registrar_licoes(discrepancias: list[dict]) -> int:
    """Converte discrepâncias em lições acionáveis (source=worker, ADR-023).

    Também persiste na tabela legada (`curator_lessons` via direction) para
    retro-compatibilidade com o Flash que ainda lê dali em
    `_construir_prompt_dinamico`. Isso garante que o curador continua evoluindo.

    Retorna quantas lições foram persistidas com sucesso.
    """
    import uuid

    novas = 0
    for d in discrepancias:
        flash_action = d["decisao_flash"].get("action", "").upper()
        direction = (
            LESSON_FLASH_APROVOU_PRO_REJEITOU if flash_action == "APPROVE"
            else LESSON_FLASH_REJEITOU_PRO_APROVOU if flash_action == "REJECT"
            else None
        )
        turno = d["turno"]

        # Legado: mantém amostra crua para o prompt do curador Flash
        if direction:
            legado = (
                f"USER: {turno.get('user_message','')[:150]} | "
                f"AGENT: {turno.get('agent_response','')[:200]} | "
                f"MOTIVO: {d.get('justificativa','')}"
            )
            try:
                await staging_store.salvar_licao(direction, legado)
            except Exception:
                logger.exception("Falha ao salvar lição legada")

        # Nova arquitetura (ADR-023): destila regra acionável para os agentes
        licao = await _destilar_licao_pro(d)
        if not licao:
            continue
        try:
            await staging_store.salvar_licao_golden(
                licao_id=f"w-{uuid.uuid4().hex[:12]}",
                regra=licao["regra"],
                motivo=licao["motivo"],
                aplicavel_a=licao["aplicavel_a"],
                source=LESSON_SOURCE_WORKER,
                ativa=True,
            )
            novas += 1
            logger.info(
                "[LIÇÃO worker] agentes=%s regra=%s",
                licao["aplicavel_a"], licao["regra"][:120],
            )
        except Exception:
            logger.exception("Falha ao salvar lição worker")

    # Invalida cache de regras no hot path para que a lição recém-criada
    # entre nos próximos prompts sem precisar reiniciar a API.
    if novas:
        try:
            from src.infrastructure.learned_memory import invalidar_cache_regras
            invalidar_cache_regras()
        except Exception:
            logger.exception("Falha ao invalidar cache de regras")

    return novas


# ── Processamento de um batch ────────────────────────────────────────────

_batch_counter = 0


async def processar_batch(batch_size: int) -> dict[str, int]:
    """Lê pendentes, classifica com Flash, audita com Pro, persiste resultado.

    Retorna dict com contadores do batch.
    """
    global _batch_counter
    turnos = await staging_store.listar_pendentes(limit=batch_size)
    if not turnos:
        return {"total": 0, "approved": 0, "rejected": 0, "grouped": 0}

    _batch_counter += 1
    logger.info(
        "[BATCH #%d] Processando %d turnos pendentes",
        _batch_counter, len(turnos),
    )

    # Short-circuit: turnos com thumbs-down são automaticamente rejeitados
    # e viram padrões dinâmicos (Camada 2) — não gastamos Flash neles.
    padroes_novos: list[str] = []
    auto_rejeitados: list[dict] = []
    para_classificar: list[dict] = []
    for t in turnos:
        if t.get("user_feedback") == -1:
            auto_rejeitados.append(t)
            padroes_novos.append((t.get("agent_response") or "")[:250])
        else:
            para_classificar.append(t)

    # Auditoria: registra as auto-rejeições por thumbs-down.
    # Sem indexação vetorial — só audit trail em SQLite (ADR-023).
    for t in auto_rejeitados:
        await staging_store.salvar_decisao(
            turno_id=t["id"],
            action=ACTION_AUTO_THUMBS_DOWN,
            source=SOURCE_AUTO,
            batch_number=_batch_counter,
            reason="user_feedback=-1",
            intent=t.get("intent"),
            cpf=t.get("cpf"),
            vector_collection=None,
        )

    decisoes_flash = await classificar_batch_flash(para_classificar) if para_classificar else []
    por_id = {d.get("id"): d for d in decisoes_flash if d.get("id")}

    aprovados_ids: list[str] = []
    rejeitados_ids: list[str] = [t["id"] for t in auto_rejeitados]
    agrupados_ids: list[str] = []
    aprovados_payload: list[dict] = []
    rejeitados_payload: list[dict] = list(auto_rejeitados)

    # IMPORTANTE (ADR-023): não indexamos mais turnos brutos em coleções vetoriais.
    # Respostas reais do agente contêm números volatéis (limite R$, score, cotação)
    # que virariam "verdade" na memória semântica e causariam alucinação futura.
    # A memória semântica só guarda padrões abstratos (routing, templates com
    # placeholders, lições destiladas). A decisão aqui fica apenas no audit trail SQLite.
    for t in para_classificar:
        d = por_id.get(t["id"]) or {}
        action = (d.get("action") or "").upper()
        reason = (d.get("reason") or "")[:250]
        if action == ACTION_APPROVE:
            aprovados_ids.append(t["id"])
            aprovados_payload.append(t)
            await staging_store.salvar_decisao(
                turno_id=t["id"], action=ACTION_APPROVE, source=SOURCE_FLASH,
                batch_number=_batch_counter, reason=reason,
                intent=t.get("intent"), cpf=t.get("cpf"),
                vector_collection=None,  # sem indexação vetorial — ver ADR-023
            )
        elif action == ACTION_GROUP:
            agrupados_ids.append(t["id"])
            await staging_store.salvar_decisao(
                turno_id=t["id"], action=ACTION_GROUP, source=SOURCE_FLASH,
                batch_number=_batch_counter, reason=reason,
                intent=t.get("intent"), cpf=t.get("cpf"),
            )
        else:
            rejeitados_ids.append(t["id"])
            rejeitados_payload.append(t)
            await staging_store.salvar_decisao(
                turno_id=t["id"], action=ACTION_REJECT, source=SOURCE_FLASH,
                batch_number=_batch_counter, reason=reason or "flash_reject",
                intent=t.get("intent"), cpf=t.get("cpf"),
                vector_collection=None,  # sem indexação vetorial — ver ADR-023
            )

    # Camada 1 — Pro audita a cada N batches
    if _batch_counter % PRO_AUDIT_EVERY == 0 and decisoes_flash:
        try:
            discrepancias = await pro_auditar(para_classificar, decisoes_flash)
            if discrepancias:
                logger.info("[PRO AUDIT] %d discrepâncias encontradas", len(discrepancias))
                await registrar_licoes(discrepancias)
                for d in discrepancias:
                    turno = d["turno"]
                    await staging_store.salvar_decisao(
                        turno_id=turno["id"],
                        action=ACTION_PRO_OVERRIDE,
                        source=SOURCE_PRO,
                        batch_number=_batch_counter,
                        reason=d.get("justificativa", "")[:250],
                        intent=turno.get("intent"),
                        cpf=turno.get("cpf"),
                    )
        except Exception:
            logger.exception("Falha na auditoria Pro (continuando)")

    # Camada 2 — padrões dinâmicos a partir de thumbs-down e rejeições
    for pat in padroes_novos:
        try:
            await staging_store.salvar_padrao(pat, source="thumbs_down")
        except Exception:
            logger.exception("Falha ao salvar padrão dinâmico")

    # NB (ADR-023): removemos intencionalmente a indexação de turnos brutos em
    # `COLLECTION_CURADAS` e `COLLECTION_FEEDBACK_NEG`. Esses turnos contêm
    # valores concretos de cliente (limite R$, score, cotações) que virariam
    # "verdade" na memória semântica e levariam a alucinação em respostas
    # futuras. O conhecimento destilado é persistido via:
    #   - lições abstratas em `curator_lessons` (source=worker) quando o Pro
    #     discorda do Flash (ver `registrar_licoes`);
    #   - padrões dinâmicos em `curator_dynamic_patterns` (Camada 2) a partir
    #     de thumbs-down, para alimentar o próprio prompt do curador.
    # Turnos brutos permanecem no SQLite (`memory_staging`) para auditoria
    # humana via dashboard, mas não vão para o Qdrant.
    _ = aprovados_payload  # mantido apenas para compat com rejeitados_payload
    _ = rejeitados_payload

    # Atualiza status no staging
    if aprovados_ids:
        await staging_store.marcar_status(aprovados_ids, STATUS_APPROVED)
    if rejeitados_ids:
        await staging_store.marcar_status(rejeitados_ids, STATUS_REJECTED)
    # Agrupados ficam como 'pending' por enquanto — implementação de
    # agrupamento real é um próximo passo (fora do escopo do case).

    total = len(turnos)
    approved = len(aprovados_ids)
    rejected = len(rejeitados_ids)
    grouped = len(agrupados_ids)

    # Camada 3 — stats para auto-calibração
    await staging_store.salvar_stats_batch(
        batch_number=_batch_counter,
        total=total,
        approved=approved,
        rejected=rejected,
        grouped=grouped,
    )

    logger.info(
        "[BATCH #%d] total=%d approved=%d rejected=%d grouped=%d (taxa=%.0f%%)",
        _batch_counter, total, approved, rejected, grouped,
        100.0 * approved / total if total else 0.0,
    )
    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "grouped": grouped,
    }


# ── Loop principal ────────────────────────────────────────────────────────

async def loop_continuo(interval: int, batch_size: int) -> None:
    logger.info(
        "Worker Curador iniciado | interval=%ds | batch_size=%d", interval, batch_size,
    )
    while True:
        try:
            resultado = await processar_batch(batch_size)
            if resultado["total"] == 0:
                logger.debug("Nenhum turno pendente — dormindo %ds", interval)
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Erro no loop do curador (continuando)")
        await asyncio.sleep(interval)


async def rodar_uma_vez(batch_size: int) -> None:
    resultado = await processar_batch(batch_size)
    logger.info("Execução única concluída: %s", resultado)


def _configurar_logging(verbose: bool) -> None:
    """Configura console + arquivo rotativo `data/curator.log` para auditoria."""
    from logging.handlers import RotatingFileHandler

    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # Remove handlers prévios (evita duplicação em re-execuções).
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)
    root.addHandler(console)

    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
        logger.info("Log do curador persistido em %s", _LOG_PATH)
    except Exception:
        logger.exception("Não foi possível inicializar o log em arquivo (%s)", _LOG_PATH)

    for noisy in ("httpx", "httpcore", "google_genai", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Worker Curador do Banco Ágil (ver ADR-023)",
    )
    parser.add_argument("--once", action="store_true", help="Processa 1 batch e sai")
    parser.add_argument("--interval", type=int, default=30, help="Polling em segundos")
    parser.add_argument("--batch-size", type=int, default=10, help="Turnos por batch")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log DEBUG")
    args = parser.parse_args()

    _configurar_logging(args.verbose)

    if not GEMINI_API_KEY_CURATOR:
        logger.error(
            "GEMINI_API_KEY_CURATOR (ou GEMINI_API_KEY) não configurada. "
            "Defina no .env antes de rodar o curador."
        )
        sys.exit(1)

    try:
        if args.once:
            asyncio.run(rodar_uma_vez(args.batch_size))
        else:
            asyncio.run(loop_continuo(args.interval, args.batch_size))
    except KeyboardInterrupt:
        logger.info("Curador interrompido pelo usuário.")


if __name__ == "__main__":
    main()
