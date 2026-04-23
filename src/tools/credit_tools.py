"""Tools de crédito expostas como @tool para o LangGraph.

Separa as operações de negócio (registrar pedido, verificar elegibilidade)
das operações de I/O puras do csv_repository. Essas tools são chamadas
pelo modelo Flash na Fase 1 do pipeline Flash→Pro.

O modelo nunca decide o score ou status — apenas chama estas tools com os
dados que coletou da conversa, e as tools aplicam a lógica determinística.
"""
from __future__ import annotations

from langchain_core.tools import tool

from src.config import SCORE_MINIMO_APROVACAO
from src.tools.csv_repository import (
    atualizar_status_solicitacao,
    registrar_solicitacao,
)
from src.tools.score_calculator import score_aprovado


@tool
def verificar_elegibilidade_aumento(
    score_atual: int,
    limite_atual: float,
    novo_limite_solicitado: float,
) -> dict:
    """Verifica se o score atual permite o aumento de limite solicitado.

    Aplica a regra de negócio: score ≥ 500 → elegível para qualquer aumento.
    Não consulta APIs externas — cálculo puramente determinístico.

    Args:
        score_atual: Score de crédito atual do cliente (0-1000).
        limite_atual: Limite de crédito atual em reais.
        novo_limite_solicitado: Novo limite desejado pelo cliente em reais.

    Returns:
        dict com "elegivel" (bool), "score_atual" (int),
        "score_minimo" (int) e "motivo" (str).
    """
    elegivel = score_aprovado(score_atual)
    return {
        "elegivel": elegivel,
        "score_atual": score_atual,
        "score_minimo": SCORE_MINIMO_APROVACAO,
        "limite_atual": limite_atual,
        "novo_limite_solicitado": novo_limite_solicitado,
        "motivo": (
            f"Score {score_atual} ≥ {SCORE_MINIMO_APROVACAO} — aprovado."
            if elegivel
            else f"Score {score_atual} < {SCORE_MINIMO_APROVACAO} — reprovado. "
                 f"Diferença: {SCORE_MINIMO_APROVACAO - score_atual} pontos."
        ),
    }


@tool
def registrar_pedido_aumento(
    cpf: str,
    limite_atual: float,
    novo_limite_solicitado: float,
    status: str,
) -> dict:
    """Registra uma solicitação de aumento de limite no sistema.

    Persiste em solicitacoes_aumento_limite.csv conforme especificado no case.

    Args:
        cpf: CPF do cliente (com ou sem máscara).
        limite_atual: Limite de crédito atual em reais.
        novo_limite_solicitado: Novo limite desejado em reais.
        status: "aprovado", "reprovado" ou "pendente".

    Returns:
        dict com "sucesso" (bool), "protocolo" (str) e "status" (str).
    """
    try:
        protocolo = registrar_solicitacao(
            cpf=cpf,
            limite_atual=limite_atual,
            novo_limite=novo_limite_solicitado,
            status=status,
        )
        return {
            "sucesso": True,
            "protocolo": str(protocolo),
            "status": status,
            "mensagem": f"Solicitação registrada com status '{status}'.",
        }
    except Exception as exc:
        return {
            "sucesso": False,
            "protocolo": "",
            "status": status,
            "mensagem": f"Erro ao registrar: {exc}",
        }
