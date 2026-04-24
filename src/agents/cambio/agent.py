"""Agente de Câmbio — cotação de moedas em tempo real via Tavily.

A tool call é executada inline neste nó: o LLM chama a tool, a tool
executa, o resultado é injetado no histórico e o LLM responde com o
valor final. O router nunca vê uma AIMessage com tool_calls pendentes.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.few_shot import buscar_exemplos_curados
from src.infrastructure.model_provider import criar_llm, invocar_com_fallback, normalizar_content
from src.models.state import BancoAgilState
from src.tools.exchange_rate import criar_tool_cambio

from .contract import contrato_cotacao
from .prompt import build_system_prompt

logger = logging.getLogger(__name__)

_tool_cambio = criar_tool_cambio()
_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo"}
_INTENCOES_CREDITO = {"crédito", "credito", "limite", "aumento"}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|encaminh)",
    re.IGNORECASE,
)

# Padrões para extrair valor numérico do resultado do Tavily.
# O Tavily retorna formatos variados: "5,13 Real Brasileiro", "1 EUR = 5,8173 BRL",
# "USD/BRL 5.13" etc. — nenhum com "R$". Por isso extraímos programaticamente.
_RE_VALOR_CAMBIO = re.compile(
    r"""
    (?:
        (?:=|é|hoje[:\s]+|atual[:\s]+|agora[:\s]+|taxa[:\s]+)  # prefixo contextual
        \s*
    )?
    (?:R\$\s*)?                        # R$ opcional
    (\d{1,3}(?:[.,]\d{3})*[.,]\d{2,4}) # valor: 5,13 | 5.1320 | 5.845 | 1.234,56
    \s*
    (?:BRL|reais|real|R\$)?            # sufixo opcional
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Mapa de queries confiáveis por moeda (descobertas via diagnóstico Tavily).
# Ordem de preferência: da mais confiável para fallback.
# JPY é caso especial: 1 JPY ≈ 0,03 BRL — buscamos "100 JPY" para obter valor > 1.
_QUERIES_CONFIAVEIS: dict[str, list[str]] = {
    "USD": [
        "USD BRL exchange rate today",
        "dólar americano hoje preço BRL",
        "USD para BRL hoje",
        "dólar hoje real brasileiro",
    ],
    "EUR": [
        "cotação euro hoje em reais",
        "EUR BRL hoje",
        "euro real exchange rate",
    ],
    "GBP": [
        "GBP BRL exchange rate",
        "libra esterlina real exchange rate today",
        "GBP to BRL today",
    ],
    "JPY": [
        "100 JPY to BRL exchange rate",
        "iene japonês 100 unidades reais",
        "JPY BRL 100 yen",
    ],
    "CAD": [
        "dólar canadense hoje em reais",
        "CAD BRL exchange rate",
    ],
}

# Palavras-chave para detectar a moeda na query original do LLM
_KEYWORDS_MOEDA: list[tuple[str, list[str]]] = [
    ("USD", ["dólar", "dollar", "usd", "dolar"]),
    ("EUR", ["euro", "eur"]),
    ("GBP", ["libra", "gbp", "pound", "sterling"]),
    ("JPY", ["iene", "jpy", "yen", "japonês", "japones"]),
    ("CAD", ["canadense", "cad", "canadian"]),
]


def _detectar_moeda(query: str) -> str | None:
    """Detecta a moeda pelo texto da query do LLM."""
    query_lower = query.lower()
    for moeda, keywords in _KEYWORDS_MOEDA:
        if any(kw in query_lower for kw in keywords):
            return moeda
    return None


def _extrair_valor_tavily(resultado_str: str, moeda: str | None = None) -> str | None:
    """Extrai o valor numérico de câmbio do resultado bruto do Tavily.

    Normaliza para o formato brasileiro (vírgula decimal, 2 casas).
    Retorna None se não encontrar nenhum valor.

    Para JPY: buscamos "100 JPY = X BRL" onde X > 1.0, e retornamos X.
    Para demais moedas: buscamos valores no range 1.0–30.0 BRL.
    """
    # JPY: 1 JPY ≈ 0,033 BRL — buscamos especificamente "100 JPY X BRL".
    # Forbes Advisor retorna: "100 JPY 3.1187 BRL" — usamos esse como valor apresentado.
    if moeda == "JPY":
        # Padrão prioritário: "100 JPY X.XXXX BRL" (Forbes Advisor)
        match_100 = re.search(
            r"100\s*JPY\s+(\d+[.,]\d+)\s*BRL",
            resultado_str,
            re.IGNORECASE,
        )
        if match_100:
            raw = match_100.group(1)
            normalizado = raw.replace(".", ",") if "." in raw and "," not in raw else raw
            try:
                val = float(normalizado.replace(".", "").replace(",", "."))
                if 0.5 <= val <= 20.0:
                    return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except ValueError:
                pass
        # Fallback: qualquer valor no range de 100 JPY (~2–6 BRL)
        matches_jpy = _RE_VALOR_CAMBIO.findall(resultado_str)
        candidatos_jpy = []
        for m in matches_jpy:
            normalizado = m.replace(".", ",") if "." in m and "," not in m else m
            try:
                val = float(normalizado.replace(".", "").replace(",", "."))
                if 2.0 <= val <= 8.0:
                    candidatos_jpy.append((val, normalizado))
            except ValueError:
                continue
        if candidatos_jpy:
            _, melhor = candidatos_jpy[0]
            try:
                val = float(melhor.replace(".", "").replace(",", "."))
                return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except ValueError:
                return melhor
        return None

    # Demais moedas: range 1.0–30.0 BRL por unidade
    matches = _RE_VALOR_CAMBIO.findall(resultado_str)
    candidatos = []
    for m in matches:
        normalizado = m.replace(".", ",") if "." in m and "," not in m else m
        try:
            valor_float = float(normalizado.replace(".", "").replace(",", "."))
            if 1.0 <= valor_float <= 30.0:
                candidatos.append((valor_float, normalizado))
        except ValueError:
            continue

    if not candidatos:
        return None

    # Pega o primeiro valor — em dados financeiros o texto menciona a taxa atual primeiro.
    _, melhor = candidatos[0]

    try:
        val = float(melhor.replace(".", "").replace(",", "."))
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return melhor


def no_cambio(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Câmbio.

    Executa o ciclo completo de tool calling em um único turno:
    1. LLM decide chamar a tool de câmbio
    2. Tool executa e retorna o resultado
    3. LLM recebe o resultado e formula a resposta final
    O router só vê a AIMessage final (sem tool_calls pendentes).
    """
    llm = criar_llm().bind_tools([_tool_cambio])

    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
        return {"encerrado": True, "resposta_final": None}

    if any(p in ultima_msg_lower for p in _INTENCOES_CREDITO):
        return {"agente_ativo": "credito", "resposta_final": None}

    nome = cliente.get("nome", "Cliente").split()[0]
    memorias = state.get("memoria_cliente") or []
    exemplos_curados = buscar_exemplos_curados(ultima_msg, intent="cambio")

    messages = [
        SystemMessage(
            content=build_system_prompt(cliente, memorias, exemplos_curados),
        )
    ] + list(state["messages"])

    # ── 1ª chamada: LLM decide se precisa da tool ────────────────────────────
    try:
        resposta_inicial = llm.invoke(messages)
    except Exception as exc:
        logger.error("[CAMBIO] Falha na 1ª chamada LLM: %s", exc)
        fallback = f"{nome}, qual moeda você gostaria de consultar?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # ── Sem tool call: verificar se a pergunta é claramente sobre câmbio ────
    if not getattr(resposta_inicial, "tool_calls", None):
        texto = normalizar_content(resposta_inicial.content).strip()
        if _RE_HANDOFF.search(texto):
            logger.warning("[CAMBIO] Handoff detectado — descartado: %.100s", texto)
            texto = f"{nome}, qual moeda você gostaria de consultar? Posso verificar dólar, euro, libra e outras."
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

        # Se a pergunta menciona explicitamente uma moeda mas o LLM não chamou a tool,
        # é um erro de roteamento do LLM (contexto poluído). Forçamos a chamada.
        moeda_na_msg = _detectar_moeda(ultima_msg)
        if moeda_na_msg:
            logger.warning(
                "[CAMBIO] LLM não chamou a tool para mensagem sobre %s — forçando tool call",
                moeda_na_msg,
            )
            queries_para_forcar = _QUERIES_CONFIAVEIS.get(moeda_na_msg, [])
            query_forcada = queries_para_forcar[0] if queries_para_forcar else f"{moeda_na_msg} BRL exchange rate today"
            # Injeta instrução explícita e re-invoca
            msgs_forcado = messages + [SystemMessage(content=(
                f"INSTRUÇÃO OBRIGATÓRIA: O cliente perguntou sobre a cotação de {moeda_na_msg}. "
                f"Você DEVE chamar a ferramenta buscar_cotacao_cambio com a query '{query_forcada}'. "
                "Não responda sem antes chamar a ferramenta."
            ))]
            try:
                resposta_forcada = llm.invoke(msgs_forcado)
                if getattr(resposta_forcada, "tool_calls", None):
                    logger.info("[CAMBIO] Tool call forçada com sucesso")
                    resposta_inicial = resposta_forcada
                    # Continua para o bloco de tool calls abaixo
                else:
                    logger.error("[CAMBIO] Tool call forçada falhou — LLM ainda sem tool call")
                    texto_fallback = f"{nome}, vou verificar a cotação de {moeda_na_msg} para você. Um momento."
                    return {"messages": [AIMessage(content=texto_fallback)], "resposta_final": texto_fallback}
            except Exception as exc:
                logger.error("[CAMBIO] Erro ao forçar tool call: %s", exc)
                return {"messages": [resposta_inicial], "resposta_final": texto}
        else:
            return {"messages": [resposta_inicial], "resposta_final": texto}

    # A partir daqui: resposta_inicial sempre tem tool_calls

    # ── Com tool call: executar inline e re-invocar ──────────────────────────
    mensagens_com_tool = messages + [resposta_inicial]
    tool_messages = []

    valor_extraido: str | None = None  # valor BR formatado extraído do Tavily

    for tc in resposta_inicial.tool_calls:
        query_original = tc.get("args", {}).get("args", {})
        args_originais = tc.get("args", {})
        query_str = args_originais.get("query", "")
        moeda_detectada = _detectar_moeda(query_str)
        logger.info("[CAMBIO] Tool call: nome=%s moeda=%s query=%s",
                    tc.get("name"), moeda_detectada, query_str)
        try:
            resultado = _tool_cambio.invoke(args_originais)
            resultado_str = str(resultado)
            logger.info("[CAMBIO] Tavily raw result (500c): %.500s", resultado_str)
            valor_extraido = _extrair_valor_tavily(resultado_str, moeda_detectada)
            logger.info("[CAMBIO] Valor extraído do Tavily: %s", valor_extraido)

            # Retry com queries confiáveis pré-definidas quando Tavily retorna sem valor numérico
            if valor_extraido is None and moeda_detectada:
                queries_fallback = _QUERIES_CONFIAVEIS.get(moeda_detectada, [])
                # Descarta a query já tentada para evitar repetição
                queries_fallback = [q for q in queries_fallback if q.lower() != query_str.lower()]
                for query_fallback in queries_fallback:
                    logger.info("[CAMBIO] Tavily sem valor — retry com query confiável: %s", query_fallback)
                    try:
                        resultado_retry = _tool_cambio.invoke({**args_originais, "query": query_fallback})
                        resultado_retry_str = str(resultado_retry)
                        logger.info("[CAMBIO] Tavily retry (500c): %.500s", resultado_retry_str)
                        valor_retry = _extrair_valor_tavily(resultado_retry_str, moeda_detectada)
                        if valor_retry:
                            logger.info("[CAMBIO] Valor extraído no retry (%s): %s", query_fallback, valor_retry)
                            resultado_str = resultado_retry_str
                            valor_extraido = valor_retry
                            break
                    except Exception as exc_retry:
                        logger.warning("[CAMBIO] Retry Tavily falhou: %s", exc_retry)
                if valor_extraido is None:
                    logger.warning("[CAMBIO] Todas as queries fallback esgotadas para %s", moeda_detectada)
            elif valor_extraido is None:
                logger.warning("[CAMBIO] Tavily sem valor e moeda não detectada para retry")

            tool_messages.append(ToolMessage(content=resultado_str, tool_call_id=tc["id"]))
        except Exception as exc:
            logger.error("Erro ao executar tool de câmbio: %s", exc)
            tool_messages.append(ToolMessage(
                content="Não foi possível obter a cotação no momento.",
                tool_call_id=tc["id"],
            ))

    # ── 2ª chamada: LLM formula resposta com resultado da tool ───────────────
    # Se extraímos o valor numericamente, injetamos como instrução adicional
    # para garantir que o LLM use "R$" no formato correto.
    msgs_2a_chamada = mensagens_com_tool + tool_messages
    if valor_extraido:
        msgs_2a_chamada = msgs_2a_chamada + [SystemMessage(content=(
            f"INSTRUÇÃO DE FORMATAÇÃO: o valor desta cotação em reais é R$ {valor_extraido}. "
            f"Use EXATAMENTE 'R$ {valor_extraido}' na sua resposta. "
            "Não use outros formatos como BRL, USD, EUR puro ou ponto decimal americano."
        ))]

    try:
        resposta_llm = invocar_com_fallback(msgs_2a_chamada)
        texto = normalizar_content(resposta_llm.content).strip()
        logger.info("[CAMBIO] LLM resposta após tool (contém R$=%s): %.300s",
                    bool(re.search(r"R\$\s*[\d.,]+", texto)), texto)
        msgs_retorno = [resposta_inicial] + tool_messages + [resposta_llm]
    except Exception as exc:
        logger.error("[CAMBIO] Falha na 2ª chamada LLM: %s", exc)
        texto = "Não consegui obter a cotação neste momento. Tente novamente em instantes."
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    if _RE_HANDOFF.search(texto):
        logger.warning("[CAMBIO] Handoff na 2ª chamada — descartado: %.100s", texto)
        texto = f"{nome}, posso ajudar com mais alguma cotação ou outra necessidade?"
        msgs_retorno = [resposta_inicial] + tool_messages + [AIMessage(content=texto)]

    # ── Contrato: garante que a resposta contenha um valor em R$ ─────────────
    contrato = contrato_cotacao()
    satisfeito, faltando = contrato.validar(texto)
    if not satisfeito:
        logger.warning(
            "[CAMBIO] Contrato não satisfeito (sem R$) | resposta_llm=%.300s",
            texto,
        )
        # Retry: pede ao LLM para reformatar com R$ explícito
        instrucao_retry = SystemMessage(content=(
            "ATENÇÃO: sua resposta não incluiu o valor da cotação em reais com o símbolo R$. "
            "Reformule a resposta incluindo o valor exato em reais usando o formato: R$ X,XX. "
            "Use os dados retornados pela ferramenta de câmbio. "
            "Não diga que houve erro — apenas apresente o valor."
        ))
        try:
            resposta_retry = invocar_com_fallback(
                mensagens_com_tool + tool_messages + [AIMessage(content=texto), instrucao_retry]
            )
            texto_retry = normalizar_content(resposta_retry.content).strip()
            logger.info("[CAMBIO] Retry contrato: %.300s", texto_retry)
            satisfeito_retry, _ = contrato.validar(texto_retry)
            if satisfeito_retry:
                logger.info("[CAMBIO] Contrato satisfeito no retry")
                texto = texto_retry
                msgs_retorno[-1] = resposta_retry
            else:
                logger.error("[CAMBIO] Contrato falhou mesmo no retry — fallback final")
                texto = f"{nome}, não consegui formatar a cotação corretamente. Por favor, tente novamente."
                msgs_retorno[-1] = AIMessage(content=texto)
        except Exception as exc:
            logger.error("[CAMBIO] Retry falhou com exceção: %s", exc)
            texto = f"{nome}, não consegui formatar a cotação corretamente. Por favor, tente novamente."
            msgs_retorno[-1] = AIMessage(content=texto)

    return {"messages": msgs_retorno, "resposta_final": texto}
