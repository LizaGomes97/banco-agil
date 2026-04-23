"""
Configuração do simulador de clientes do Banco Ágil.

Clientes espelham exatamente os dados de data/clientes.csv para que
os testes de autenticação sejam determinísticos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

# ── Conexão ───────────────────────────────────────────────────────────────────
BACKEND_URL: str = os.getenv("SIMULADOR_BACKEND_URL", "http://localhost:8000")
TIMEOUT_SEGUNDOS: float = float(os.getenv("SIMULADOR_TIMEOUT", "30"))
MAX_TENTATIVAS_AUTH: int = 3          # deve coincidir com a regra do frontend/agente

# ── Relatórios ────────────────────────────────────────────────────────────────
REPORTS_DIR: str = os.getenv("SIMULADOR_REPORTS_DIR", "simulador/reports")


# ── Clientes fictícios (dados de data/clientes.csv) ───────────────────────────
@dataclass
class ClienteSimulado:
    nome: str
    cpf: str
    data_nascimento: str          # formato DD/MM/AAAA (igual ao AuthCard)
    limite_credito: float
    score: int
    data_invalida: str = ""       # data errada para testar falha de auth


CLIENTES: List[ClienteSimulado] = [
    ClienteSimulado(
        nome="Ana Silva",
        cpf="123.456.789-00",
        data_nascimento="15/01/1990",
        limite_credito=5000.0,
        score=650,
        data_invalida="01/01/2000",
    ),
    ClienteSimulado(
        nome="Carlos Mendes",
        cpf="987.654.321-00",
        data_nascimento="22/07/1985",
        limite_credito=3000.0,
        score=320,
        data_invalida="01/01/2000",
    ),
    ClienteSimulado(
        nome="Maria Oliveira",
        cpf="456.789.123-00",
        data_nascimento="10/03/1995",
        limite_credito=8000.0,
        score=780,
        data_invalida="01/01/2000",
    ),
    ClienteSimulado(
        nome="João Santos",
        cpf="321.654.987-00",
        data_nascimento="30/11/1978",
        limite_credito=1500.0,
        score=180,
        data_invalida="01/01/2000",
    ),
    ClienteSimulado(
        nome="Fernanda Lima",
        cpf="789.123.456-00",
        data_nascimento="05/05/2000",
        limite_credito=10000.0,
        score=850,
        data_invalida="01/01/1990",
    ),
]
