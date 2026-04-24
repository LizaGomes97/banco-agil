"""LLM-as-judge — avaliação nightly da qualidade das respostas (ADR-022).

Amostra N turnos aprovados ainda não julgados, pede ao Gemini Pro que avalie
em 3 critérios (precisão, tom, completude) numa escala 1-5, e grava na tabela
`judge_scores`. Objetivo: detectar regressões ANTES do usuário reclamar.

Uso:
    python -m src.worker.judge                    # amostra 20 turnos
    python -m src.worker.judge --sample 50        # amostra 50
    python -m src.worker.judge --stats            # mostra estatísticas últimos 30d

Pensado para rodar via cron/scheduler uma vez por dia.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY_CURATOR
from src.infrastructure.staging_store import staging_store

logger = logging.getLogger("judge")


_PROMPT_JUDGE = """\
Você é um AVALIADOR sênior de qualidade de atendimento bancário.
Receberá uma interação (pergunta do cliente + resposta do agente) e deve
pontuar em 3 critérios numa escala de 1 a 5:

1. PRECISÃO (1-5): a resposta é factualmente correta, usa os dados certos,
   não alucina valores, não promete o que não pode cumprir?
2. TOM (1-5): o tom é profissional, empático, em português correto,
   sem jargões internos vazados (ex: "transferir", "especialista")?
3. COMPLETUDE (1-5): a resposta endereça o que o cliente pediu,
   sem deixar pontas soltas nem exigir follow-up desnecessário?

Responda em JSON estrito:
{"precisao": <int 1-5>, "tom": <int 1-5>, "completude": <int 1-5>, "comentario": "<1 frase>"}
"""


def _judge_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0,
        google_api_key=GEMINI_API_KEY_CURATOR,
        max_output_tokens=256,
    )


def _extrair_json(content: str) -> dict[str, Any] | None:
    txt = (content or "").strip()
    # remove fences de markdown se houver
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    match = re.search(r"\{.*\}", txt, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _clamp_1_5(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return max(1, min(5, n))


async def julgar_turno(turno: dict) -> dict | None:
    """Chama o Gemini Pro para avaliar um único turno. Retorna dict de scores ou None."""
    prompt_input = (
        f"## CLIENTE PERGUNTOU\n{turno.get('user_message','')[:600]}\n\n"
        f"## AGENTE RESPONDEU\n{turno.get('agent_response','')[:1200]}\n\n"
        f"## METADADOS\nagent={turno.get('agent_name')} intent={turno.get('intent')}"
    )
    try:
        resposta = await asyncio.to_thread(
            _judge_llm().invoke,
            [SystemMessage(content=_PROMPT_JUDGE), HumanMessage(content=prompt_input)],
        )
    except Exception:
        logger.exception("[JUDGE] Falha ao chamar LLM para turno=%s", turno.get("id"))
        return None

    parsed = _extrair_json(getattr(resposta, "content", "") or "")
    if not parsed:
        logger.warning("[JUDGE] JSON inválido para turno=%s", turno.get("id"))
        return None
    return {
        "precisao": _clamp_1_5(parsed.get("precisao")),
        "tom": _clamp_1_5(parsed.get("tom")),
        "completude": _clamp_1_5(parsed.get("completude")),
        "comentario": str(parsed.get("comentario", ""))[:500],
    }


async def rodada_julgamento(sample_size: int) -> dict:
    """Executa uma rodada: amostra + julga + persiste. Retorna resumo."""
    turnos = await staging_store.amostrar_turnos_para_julgamento(limit=sample_size)
    if not turnos:
        logger.info("[JUDGE] Nenhum turno aprovado pendente de julgamento.")
        return {"julgados": 0, "falhas": 0}

    logger.info("[JUDGE] Avaliando %d turnos aprovados", len(turnos))
    julgados = 0
    falhas = 0
    scores_totais: list[float] = []

    for turno in turnos:
        scores = await julgar_turno(turno)
        if not scores or any(scores[k] == 0 for k in ("precisao", "tom", "completude")):
            falhas += 1
            continue
        try:
            await staging_store.salvar_judge_score(
                turno_id=turno["id"],
                precisao=scores["precisao"],
                tom=scores["tom"],
                completude=scores["completude"],
                comentario=scores["comentario"],
            )
            julgados += 1
            scores_totais.append(
                (scores["precisao"] + scores["tom"] + scores["completude"]) / 3.0
            )
        except Exception:
            logger.exception("[JUDGE] Falha ao persistir score turno=%s", turno.get("id"))
            falhas += 1

    media = sum(scores_totais) / len(scores_totais) if scores_totais else 0.0
    logger.info(
        "[JUDGE] Concluído | julgados=%d | falhas=%d | media=%.2f/5",
        julgados, falhas, media,
    )
    return {"julgados": julgados, "falhas": falhas, "media": round(media, 2)}


async def mostrar_stats() -> None:
    stats = await staging_store.estatisticas_judge(days=30)
    print("=== LLM-as-judge — últimos 30 dias ===")
    for k, v in (stats or {}).items():
        print(f"  {k}: {v}")


def _configurar_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-as-judge nightly (ver ADR-022)")
    parser.add_argument("--sample", type=int, default=20, help="Turnos a avaliar")
    parser.add_argument("--stats", action="store_true", help="Mostra estatísticas e sai")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log DEBUG")
    args = parser.parse_args()
    _configurar_logging(args.verbose)

    if args.stats:
        asyncio.run(mostrar_stats())
        return

    if not GEMINI_API_KEY_CURATOR:
        logger.error("GEMINI_API_KEY_CURATOR não configurada.")
        sys.exit(1)

    asyncio.run(rodada_julgamento(args.sample))


if __name__ == "__main__":
    main()
