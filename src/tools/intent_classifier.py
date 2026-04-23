"""Classificador de intenção baseado em LLM.

Substitui o keyword matching de triagem.py por uma chamada focada ao Gemini.
Usa temperature=0 para respostas determinísticas e modelo flash para baixa latência.

Intenções possíveis:
  credito   — aumento de limite, consulta de score, empréstimo
  cambio    — cotação de moeda, câmbio, conversão
  encerrar  — despedida, encerrar atendimento
  nenhum    — intenção não identificada ou conversa genérica
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_INTENCOES_VALIDAS = {"credito", "cambio", "encerrar", "nenhum"}

_PROMPT_CLASSIFICADOR = """\
Você é um classificador de intenções para um assistente bancário digital chamado Banco Ágil.
Sua única função é identificar o que o cliente quer.

Classifique a mensagem do cliente em UMA das categorias abaixo.
Responda SOMENTE com a palavra-chave exata, sem pontuação, sem explicações.

Categorias:
- credito    → pedir aumento de limite de cartão, consultar score de crédito, falar sobre empréstimo
- cambio     → perguntar cotação de moeda (dólar, euro, libra, iene etc.), câmbio, conversão de moeda
- encerrar   → despedir-se, encerrar atendimento, tchau, sair, obrigado (finalizando)
- nenhum     → qualquer outra coisa (saudação, pergunta genérica, assunto não identificado)

Regra de desempate: se a mensagem citar câmbio/moeda E crédito ao mesmo tempo, classifique como "cambio".
"""


def classificar_intencao(mensagem: str) -> str:
    """Chama o LLM para classificar a intenção do cliente.

    Retorna uma das strings: "credito", "cambio", "encerrar", "nenhum".
    Em caso de falha na chamada ao LLM, retorna "nenhum" com log de erro.
    """
    try:
        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            temperature=0,
            google_api_key=GEMINI_API_KEY,
            max_output_tokens=10,
        )
        resposta = llm.invoke([
            SystemMessage(content=_PROMPT_CLASSIFICADOR),
            HumanMessage(content=mensagem),
        ])
        intencao = resposta.content.strip().lower().split()[0]
        if intencao not in _INTENCOES_VALIDAS:
            logger.warning("LLM retornou intenção inesperada '%s' → fallback 'nenhum'", intencao)
            return "nenhum"
        logger.debug("Intenção classificada: '%s' para mensagem: '%s'", intencao, mensagem[:60])
        return intencao
    except Exception as exc:
        logger.error("Erro no classificador de intenção: %s", exc)
        return "nenhum"
