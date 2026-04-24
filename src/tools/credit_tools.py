"""Tools de crédito expostas como @tool para o LangGraph.

Aplica lógica determinística do case:
    1. Verificação usa a tabela `score_limite.csv` (score -> limite máximo).
    2. `registrar_pedido_aumento` persiste em `solicitacoes_aumento_limite.csv`.
    3. `atualizar_limite_cliente` grava o novo limite em `clientes.csv`
        apenas quando a solicitação é aprovada.

O LLM nunca decide o resultado — ele coleta dados e chama as tools, que
retornam o status determinístico.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from src.tools.csv_repository import (
    atualizar_limite,
    consultar_limite_maximo_por_score,
    registrar_solicitacao,
)

logger = logging.getLogger(__name__)


@tool
def verificar_elegibilidade_aumento(
    score_atual: int,
    limite_atual: float,
    novo_limite_solicitado: float,
) -> dict:
    """Verifica se o score atual permite o novo limite solicitado.

    Consulta `score_limite.csv` para obter o teto da faixa de score do cliente.
    Se `novo_limite_solicitado` <= teto -> elegível; caso contrário, reprovado.

    Args:
        score_atual: Score de crédito atual do cliente (0-1000).
        limite_atual: Limite de crédito atual em reais.
        novo_limite_solicitado: Novo limite desejado em reais.

    Returns:
        dict com "elegivel" (bool), "score_atual" (int),
        "limite_maximo_permitido" (float), "limite_atual" (float),
        "novo_limite_solicitado" (float), "motivo" (str).
    """
    teto = consultar_limite_maximo_por_score(score_atual)
    if teto is None:
        return {
            "elegivel": False,
            "score_atual": score_atual,
            "limite_maximo_permitido": 0.0,
            "limite_atual": limite_atual,
            "novo_limite_solicitado": novo_limite_solicitado,
            "motivo": (
                "Não foi possível consultar a tabela de score. "
                "Tente novamente em instantes."
            ),
        }

    if novo_limite_solicitado <= limite_atual:
        return {
            "elegivel": False,
            "score_atual": score_atual,
            "limite_maximo_permitido": teto,
            "limite_atual": limite_atual,
            "novo_limite_solicitado": novo_limite_solicitado,
            "motivo": (
                f"O valor solicitado (R$ {novo_limite_solicitado:,.2f}) não é "
                f"maior que o limite atual (R$ {limite_atual:,.2f})."
            ),
        }

    elegivel = novo_limite_solicitado <= teto
    if elegivel:
        motivo = (
            f"Score {score_atual} permite limite até R$ {teto:,.2f}. "
            f"Valor solicitado R$ {novo_limite_solicitado:,.2f} aprovado."
        )
    else:
        motivo = (
            f"Score {score_atual} permite limite máximo de R$ {teto:,.2f}. "
            f"Valor solicitado R$ {novo_limite_solicitado:,.2f} excede o teto."
        )

    return {
        "elegivel": elegivel,
        "score_atual": score_atual,
        "limite_maximo_permitido": teto,
        "limite_atual": limite_atual,
        "novo_limite_solicitado": novo_limite_solicitado,
        "motivo": motivo,
    }


@tool
def registrar_pedido_aumento(
    cpf: str,
    limite_atual: float,
    novo_limite_solicitado: float,
    status: str,
) -> dict:
    """Registra uma solicitação de aumento de limite no sistema.

    Persiste em `solicitacoes_aumento_limite.csv` conforme o case.

    Args:
        cpf: CPF do cliente (com ou sem máscara).
        limite_atual: Limite atual em reais.
        novo_limite_solicitado: Novo limite desejado em reais.
        status: "aprovado", "rejeitado" ou "pendente".

    Returns:
        dict com "sucesso" (bool), "protocolo" (str) e "status" (str).
    """
    status_norm = (status or "pendente").strip().lower()
    # case usa "rejeitado"; histórico usa "reprovado" — aceitamos ambos.
    if status_norm == "reprovado":
        status_norm = "rejeitado"

    try:
        protocolo = registrar_solicitacao(
            cpf=cpf,
            limite_atual=limite_atual,
            novo_limite=novo_limite_solicitado,
            status=status_norm,
        )
        if not protocolo:
            return {
                "sucesso": False,
                "protocolo": "",
                "status": status_norm,
                "mensagem": "Falha ao persistir a solicitação no CSV.",
            }
        return {
            "sucesso": True,
            "protocolo": protocolo,
            "status": status_norm,
            "mensagem": f"Solicitação registrada com status '{status_norm}'.",
        }
    except Exception as exc:
        logger.error("Erro ao registrar pedido: %s", exc)
        return {
            "sucesso": False,
            "protocolo": "",
            "status": status_norm,
            "mensagem": f"Erro ao registrar: {exc}",
        }


@tool
def atualizar_limite_cliente(cpf: str, novo_limite: float) -> dict:
    """Atualiza o limite de crédito do cliente em `clientes.csv`.

    Deve ser chamada APENAS após `registrar_pedido_aumento` retornar
    `status=aprovado`. Não valida elegibilidade — a verificação ocorre
    em `verificar_elegibilidade_aumento`.

    Args:
        cpf: CPF do cliente.
        novo_limite: Novo limite aprovado em reais.

    Returns:
        dict com "sucesso" (bool), "novo_limite" (float) e "mensagem" (str).
    """
    try:
        ok = atualizar_limite(cpf, float(novo_limite))
        if not ok:
            return {
                "sucesso": False,
                "novo_limite": novo_limite,
                "mensagem": "Cliente não encontrado ou falha de gravação no CSV.",
            }
        return {
            "sucesso": True,
            "novo_limite": novo_limite,
            "mensagem": f"Limite atualizado para R$ {novo_limite:,.2f}.",
        }
    except Exception as exc:
        logger.error("Erro ao atualizar limite: %s", exc)
        return {
            "sucesso": False,
            "novo_limite": novo_limite,
            "mensagem": f"Erro ao atualizar: {exc}",
        }
