"""Acesso aos arquivos CSV como camada de persistência.

Todas as operações de I/O com clientes.csv e solicitacoes_aumento_limite.csv
passam por aqui. Normalização de CPF e data são feitas nesta camada.
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Optional

from src.config import CLIENTES_CSV, SCORE_LIMITE_CSV, SOLICITACOES_CSV
from src.models.schemas import Cliente, SolicitacaoAumento

logger = logging.getLogger(__name__)


# ── Helpers de normalização ───────────────────────────────────────────────────

def _normalizar_cpf(cpf: str) -> str:
    """Remove caracteres não numéricos e retorna só dígitos."""
    return re.sub(r"\D", "", cpf)


def _normalizar_data(data: str) -> str:
    """Tenta converter datas comuns para YYYY-MM-DD.

    Aceita: 01/01/1990, 1990-01-01, 01-01-1990
    """
    data = data.strip()
    # já no formato ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        return data
    # DD/MM/YYYY ou DD-MM-YYYY
    m = re.match(r"^(\d{2})[/\-](\d{2})[/\-](\d{4})$", data)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return data


# ── Clientes ──────────────────────────────────────────────────────────────────

def buscar_cliente(cpf: str, data_nascimento: str) -> Optional[Cliente]:
    """Autentica o cliente comparando CPF e data de nascimento.

    Retorna o Cliente se encontrado, None caso contrário.
    Normaliza CPF (remove máscara) e data antes de comparar.
    """
    cpf_norm = _normalizar_cpf(cpf)
    data_norm = _normalizar_data(data_nascimento)

    try:
        with open(CLIENTES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (
                    _normalizar_cpf(row["cpf"]) == cpf_norm
                    and _normalizar_data(row["data_nascimento"]) == data_norm
                ):
                    return Cliente(
                        cpf=row["cpf"],
                        nome=row["nome"],
                        data_nascimento=row["data_nascimento"],
                        limite_credito=float(row["limite_credito"]),
                        score=int(row["score"]),
                    )
    except FileNotFoundError:
        logger.error("clientes.csv não encontrado em %s", CLIENTES_CSV)
    except Exception as exc:
        logger.error("Erro ao ler clientes.csv: %s", exc)

    return None


def _atualizar_campo_cliente(cpf: str, campo: str, valor: str) -> bool:
    """Atualiza um campo específico do cliente no CSV.

    Usado internamente por `atualizar_score` e `atualizar_limite` para
    evitar duplicação de lógica de leitura/reescrita.
    """
    cpf_norm = _normalizar_cpf(cpf)
    linhas: list[dict] = []
    atualizado = False

    try:
        with open(CLIENTES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if _normalizar_cpf(row["cpf"]) == cpf_norm:
                    row[campo] = valor
                    atualizado = True
                linhas.append(row)

        if atualizado:
            with open(CLIENTES_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(linhas)

    except Exception as exc:
        logger.error("Erro ao atualizar %s do cliente: %s", campo, exc)
        return False

    return atualizado


def atualizar_score(cpf: str, novo_score: int) -> bool:
    """Atualiza o score do cliente no CSV após entrevista de crédito."""
    return _atualizar_campo_cliente(cpf, "score", str(novo_score))


def atualizar_limite(cpf: str, novo_limite: float) -> bool:
    """Atualiza o limite de crédito do cliente no CSV após aprovação."""
    return _atualizar_campo_cliente(cpf, "limite_credito", f"{novo_limite:.2f}")


# ── Tabela score -> limite máximo ────────────────────────────────────────────

def consultar_limite_maximo_por_score(score: int) -> Optional[float]:
    """Consulta o limite máximo aprovável para um dado score.

    Lê `score_limite.csv` que define faixas (score_min, score_max, limite_maximo).
    Retorna o limite máximo da faixa em que o score se encontra, ou None se o
    arquivo não existir ou o score estiver fora de todas as faixas.
    """
    try:
        with open(SCORE_LIMITE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                smin = int(row["score_min"])
                smax = int(row["score_max"])
                if smin <= score <= smax:
                    return float(row["limite_maximo"])
    except FileNotFoundError:
        logger.error("score_limite.csv não encontrado em %s", SCORE_LIMITE_CSV)
    except Exception as exc:
        logger.error("Erro ao ler score_limite.csv: %s", exc)
    return None


# ── Solicitações ──────────────────────────────────────────────────────────────

def registrar_solicitacao(
    cpf: str,
    limite_atual: float,
    novo_limite: float,
    status: str = "pendente",
) -> Optional[str]:
    """Registra uma nova solicitação de aumento de limite em CSV.

    Retorna o id da solicitação (protocolo) em sucesso, None em falha.
    Normaliza cpf antes de persistir.
    """
    solicitacao = SolicitacaoAumento(
        cpf=_normalizar_cpf(cpf),
        limite_atual=float(limite_atual),
        limite_solicitado=float(novo_limite),
        status=status,
    )
    existe = SOLICITACOES_CSV.exists()

    try:
        with open(SOLICITACOES_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(solicitacao.to_dict().keys()))
            if not existe or SOLICITACOES_CSV.stat().st_size == 0:
                writer.writeheader()
            writer.writerow(solicitacao.to_dict())
        return solicitacao.id
    except Exception as exc:
        logger.error("Erro ao registrar solicitação: %s", exc)
        return None


def atualizar_status_solicitacao(solicitacao_id: str, novo_status: str) -> bool:
    """Atualiza o status de uma solicitação existente pelo ID."""
    linhas: list[dict] = []
    atualizado = False

    try:
        with open(SOLICITACOES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                if row["id"] == solicitacao_id:
                    row["status"] = novo_status
                    atualizado = True
                linhas.append(row)

        if atualizado:
            with open(SOLICITACOES_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(linhas)

    except Exception as exc:
        logger.error("Erro ao atualizar status: %s", exc)
        return False

    return atualizado


# ── Leads ─────────────────────────────────────────────────────────────────────

def registrar_lead(nome: str, cpf: str, telefone: str, limite_desejado: float = 0.0) -> bool:
    """Registra um lead (não cliente) que solicitou cadastro.

    Ver ADR-008 para justificativa da feature de lead capture.
    """
    from datetime import datetime
    from src.config import DATA_DIR

    leads_csv = DATA_DIR / "leads.csv"
    existe = leads_csv.exists() and leads_csv.stat().st_size > 0

    lead = {
        "nome": nome.strip(),
        "cpf": cpf.strip(),
        "telefone": telefone.strip(),
        "limite_desejado": limite_desejado,
        "criado_em": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        with open(leads_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(lead.keys()))
            if not existe:
                writer.writeheader()
            writer.writerow(lead)
        logger.info("Lead registrado: %s", cpf)
        return True
    except Exception as exc:
        logger.error("Erro ao registrar lead: %s", exc)
        return False
