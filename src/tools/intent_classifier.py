"""Classificador de intenção baseado em LLM.

Substitui o keyword matching de triagem.py por uma chamada focada ao Gemini.
Usa temperature=0 para respostas determinísticas e modelo flash para baixa latência.

Intenções possíveis:
  credito   — aumento de limite, consulta de score, empréstimo
  cambio    — cotação de moeda, câmbio, conversão
  encerrar  — despedida, encerrar atendimento
  nenhum    — intenção não identificada ou conversa genérica

Estratégia de resiliência:
  1. Tenta LLM com max_output_tokens=10
  2. Se content vier vazio, retry com max_output_tokens=20 (evita corte prematuro)
  3. Se LLM falhar ou retornar lixo, cai em heurística por keywords
  4. Só retorna "nenhum" se NENHUMA camada conseguir classificar
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.infrastructure.cache import CacheComTTL, com_cache
from src.infrastructure.learned_memory import buscar_routing_similar, sugerir_intent_direto
from src.infrastructure.model_provider import normalizar_content

logger = logging.getLogger(__name__)

_INTENCOES_VALIDAS = {"credito", "cambio", "encerrar", "nenhum"}

# Cache de 5 minutos — mensagens idênticas não disparam nova chamada LLM
_cache_intencao = CacheComTTL(ttl_segundos=300, max_tamanho=512)

# Métricas (thread-safe) — expostas via /api/debug/metrics
_metricas_lock = threading.Lock()
_metricas = {
    "total": 0,
    "por_intencao": Counter(),
    "llm_ok": 0,
    "llm_vazio_retry": 0,
    "llm_falha": 0,
    "heuristica_acerto": 0,
    "fallback_nenhum": 0,
    "golden_shortcut": 0,     # intent resolvido direto via k-NN golden (sem LLM)
    "golden_fewshot_hit": 0,  # LLM usou hints do routing golden
}


def obter_metricas() -> dict:
    """Snapshot das métricas do classificador para endpoint de debug."""
    with _metricas_lock:
        return {
            "total": _metricas["total"],
            "por_intencao": dict(_metricas["por_intencao"]),
            "llm_ok": _metricas["llm_ok"],
            "llm_vazio_retry": _metricas["llm_vazio_retry"],
            "llm_falha": _metricas["llm_falha"],
            "heuristica_acerto": _metricas["heuristica_acerto"],
            "fallback_nenhum": _metricas["fallback_nenhum"],
            "golden_shortcut": _metricas.get("golden_shortcut", 0),
            "golden_fewshot_hit": _metricas.get("golden_fewshot_hit", 0),
        }


def _inc_metrica(chave: str, valor: int = 1) -> None:
    with _metricas_lock:
        _metricas[chave] = _metricas.get(chave, 0) + valor


def _inc_intencao(intencao: str) -> None:
    with _metricas_lock:
        _metricas["total"] += 1
        _metricas["por_intencao"][intencao] += 1


# ── Heurística de fallback quando o LLM falha ─────────────────────────────────
# Ordem importa: "cambio" antes de "credito" para resolver desempates
# (mensagens como "quero trocar meus reais por dólar para comprar no crédito")

_REGEX_ENCERRAR = re.compile(
    r"\b(encerrar|tchau|sair|at[eé]\s+(logo|mais)|obrigad[oa](\s+por\s+tudo)?$|"
    r"finalizar|terminar\s+atendimento)\b",
    re.IGNORECASE,
)

_REGEX_CAMBIO = re.compile(
    r"\b(c[âa]mbio|cota[çc][ãa]o|d[óo]lar|euro|libra|iene|ienes|peso|yuan|"
    r"franco|usd|eur|gbp|jpy|cad|chf|convers[ãa]o\s+de\s+moeda|trocar?\s+.*"
    r"(d[óo]lar|euro|moeda|real))\b",
    re.IGNORECASE,
)

# "credito" só dispara quando há intent de AÇÃO (aumentar, pedir, solicitar, empréstimo)
# Consultas simples ("qual meu limite?", "meu score?") NÃO devem cair em credito.
_REGEX_CREDITO_ACAO = re.compile(
    r"\b(aument(ar|o|e)|pedir|solicitar?|quero\s+(um\s+)?empr[ée]stimo|"
    r"empr[ée]stimo|novo\s+limite|mais\s+limite|expandir\s+(meu\s+)?limite|"
    r"subir\s+(meu\s+)?(limite|cr[ée]dito)|pretendo\s+aumentar)\b",
    re.IGNORECASE,
)


def _classificar_por_keywords(mensagem: str) -> str:
    """Heurística de fallback. Retorna 'nenhum' se nada casar."""
    texto = mensagem.strip()
    if not texto:
        return "nenhum"

    if _REGEX_ENCERRAR.search(texto):
        return "encerrar"
    if _REGEX_CAMBIO.search(texto):
        return "cambio"
    if _REGEX_CREDITO_ACAO.search(texto):
        return "credito"
    return "nenhum"


_PROMPT_CLASSIFICADOR = """\
Você é um classificador de intenções para um assistente bancário digital chamado Banco Ágil.
Sua única função é identificar o que o cliente quer.

Classifique a mensagem do cliente em UMA das categorias abaixo.
Responda SOMENTE com a palavra-chave exata, sem pontuação, sem explicações.

Categorias:
- credito    → pedir AUMENTO de limite de crédito/cartão, solicitar empréstimo, consultar elegibilidade de crédito
- cambio     → perguntar cotação de moeda (dólar, euro, libra, iene etc.), câmbio, conversão de moeda
- encerrar   → despedir-se, encerrar atendimento, tchau, sair, obrigado (finalizando)
- nenhum     → qualquer outra coisa: saudações, consultas de saldo, consulta de limite atual, consulta de score atual, informações gerais, assunto não identificado

ATENÇÃO — classificar como "nenhum" (NÃO como "credito"):
- "quero saber meu saldo"
- "qual meu limite atual?"
- "qual meu score?"
- "qual é o meu limite de crédito?"
- perguntas que APENAS consultam informações, sem PEDIR AUMENTO ou EMPRÉSTIMO

IMPORTANTE — mensagens com MÚLTIPLAS intenções:
- Se o cliente cita consulta + ação de aumento (ex: "quero ver meu score e aumentar meu limite"),
  classifique como "credito" (a ação prevalece sobre a consulta).
- Se cita câmbio + crédito ao mesmo tempo, classifique como "cambio".
"""


def _montar_few_shot_routing(mensagem: str) -> tuple[str, bool]:
    """Constrói um bloco de exemplos baseado no golden set de roteamento.

    Retorna (bloco, houve_golden). Se não houver hits, retorna ("", False) e o
    LLM usa só o prompt base.
    """
    hits = buscar_routing_similar(mensagem, k=3)
    if not hits:
        return "", False
    linhas = ["\n\n## Exemplos similares (golden set)"]
    houve_golden = False
    for h in hits:
        if h.get("source") == "golden":
            houve_golden = True
        intent = h.get("intent") or "?"
        exemplo = (h.get("exemplo") or "").replace("\n", " ")[:200]
        linhas.append(f"- \"{exemplo}\" → {intent}")
    return "\n".join(linhas), houve_golden


def _invocar_llm(mensagem: str, max_tokens: int, few_shot_block: str = "") -> str:
    """Invoca o LLM e retorna a primeira palavra do content (ou string vazia)."""
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=0,
        google_api_key=GEMINI_API_KEY,
        max_output_tokens=max_tokens,
    )
    system_prompt = _PROMPT_CLASSIFICADOR + (few_shot_block or "")
    resposta = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=mensagem),
    ])
    bruto = normalizar_content(resposta.content).strip().lower()
    if not bruto:
        return ""
    tokens = bruto.split()
    return tokens[0] if tokens else ""


@com_cache(_cache_intencao, chave_fn=lambda msg: msg.strip().lower())
def classificar_intencao(mensagem: str) -> str:
    """Chama o LLM para classificar a intenção do cliente.

    Retorna uma das strings: "credito", "cambio", "encerrar", "nenhum".

    Camadas de resiliência:
      1. LLM com max_tokens=10 → maioria dos casos
      2. Se vazio: retry com max_tokens=20 (Gemini às vezes corta o primeiro token)
      3. Se LLM falha ou retorna inválido: heurística por keywords
      4. Só retorna "nenhum" se a heurística também não identificar
    """
    intencao: str | None = None

    # Camada 0 — shortcut via golden routing: se k-NN top-1 está muito forte
    # (score pós-boost >= threshold), o intent é resolvido sem chamar o LLM.
    try:
        shortcut = sugerir_intent_direto(mensagem)
        if shortcut and shortcut in _INTENCOES_VALIDAS:
            _inc_metrica("golden_shortcut")
            _inc_intencao(shortcut)
            logger.info(
                "Intenção resolvida via GOLDEN shortcut: '%s' para '%.60s'",
                shortcut, mensagem,
            )
            return shortcut
    except Exception:
        logger.exception("Falha no golden shortcut (ignorando)")

    # Monta bloco de few-shot para o LLM (se houver routing similar)
    try:
        few_shot_block, houve_golden = _montar_few_shot_routing(mensagem)
    except Exception:
        few_shot_block, houve_golden = "", False
    if houve_golden:
        _inc_metrica("golden_fewshot_hit")

    try:
        intencao = _invocar_llm(mensagem, max_tokens=10, few_shot_block=few_shot_block)
        if not intencao:
            logger.warning(
                "LLM retornou content vazio para '%.80s' — retry com max_tokens=20",
                mensagem,
            )
            _inc_metrica("llm_vazio_retry")
            intencao = _invocar_llm(mensagem, max_tokens=20, few_shot_block=few_shot_block)

        if intencao in _INTENCOES_VALIDAS:
            _inc_metrica("llm_ok")
            _inc_intencao(intencao)
            logger.debug("Intenção classificada via LLM: '%s' para '%.60s'", intencao, mensagem)
            return intencao

        if intencao:
            logger.warning(
                "LLM retornou intenção inválida '%s' — recorrendo à heurística",
                intencao,
            )
    except Exception:
        _inc_metrica("llm_falha")
        logger.exception("Falha no LLM do classificador — recorrendo à heurística")

    heuristica = _classificar_por_keywords(mensagem)
    if heuristica != "nenhum":
        _inc_metrica("heuristica_acerto")
        _inc_intencao(heuristica)
        logger.info(
            "Intenção classificada via HEURÍSTICA: '%s' para '%.60s'",
            heuristica,
            mensagem,
        )
        return heuristica

    _inc_metrica("fallback_nenhum")
    _inc_intencao("nenhum")
    logger.info("Classificador não identificou intenção para '%.80s'", mensagem)
    return "nenhum"
