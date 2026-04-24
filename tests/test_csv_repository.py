"""Testes unitários para o repositório CSV.

Usa tmp_path do pytest para não tocar nos arquivos reais.
"""
import csv
import pytest
from pathlib import Path
from unittest.mock import patch

from src.models.schemas import Cliente, SolicitacaoAumento


@pytest.fixture
def clientes_csv(tmp_path) -> Path:
    """Cria um clientes.csv temporário com dados de teste."""
    csv_path = tmp_path / "clientes.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["cpf", "nome", "data_nascimento", "limite_credito", "score"]
        )
        writer.writeheader()
        writer.writerow({
            "cpf": "123.456.789-00",
            "nome": "Ana Silva",
            "data_nascimento": "1990-01-15",
            "limite_credito": "5000.00",
            "score": "650",
        })
        writer.writerow({
            "cpf": "987.654.321-00",
            "nome": "Carlos Mendes",
            "data_nascimento": "1985-07-22",
            "limite_credito": "3000.00",
            "score": "320",
        })
    return csv_path


@pytest.fixture
def solicitacoes_csv(tmp_path) -> Path:
    """Cria um solicitacoes.csv temporário vazio."""
    csv_path = tmp_path / "solicitacoes_aumento_limite.csv"
    csv_path.write_text(
        "id,cpf,limite_atual,limite_solicitado,status,criado_em\n",
        encoding="utf-8"
    )
    return csv_path


class TestBuscarCliente:
    def test_autenticacao_bem_sucedida(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("123.456.789-00", "1990-01-15")
        assert cliente is not None
        assert cliente.nome == "Ana Silva"
        assert cliente.score == 650

    def test_cpf_sem_mascara(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("12345678900", "1990-01-15")
        assert cliente is not None

    def test_data_formato_br(self, clientes_csv):
        """Data no formato DD/MM/YYYY deve funcionar."""
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("123.456.789-00", "15/01/1990")
        assert cliente is not None

    def test_cliente_nao_encontrado(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("000.000.000-00", "1990-01-01")
        assert cliente is None

    def test_data_incorreta(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("123.456.789-00", "1990-01-01")
        assert cliente is None


class TestRegistrarSolicitacao:
    def test_registra_com_sucesso(self, solicitacoes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "SOLICITACOES_CSV", solicitacoes_csv):
            protocolo = csv_repository.registrar_solicitacao(
                cpf="123.456.789-00",
                limite_atual=5000.0,
                novo_limite=10000.0,
                status="aprovado",
            )
        assert isinstance(protocolo, str) and len(protocolo) >= 4

        with open(solicitacoes_csv, encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        assert len(linhas) == 1
        assert linhas[0]["status"] == "aprovado"
        # cpf é normalizado (apenas dígitos) na persistência
        assert linhas[0]["cpf"] == "12345678900"
        assert linhas[0]["id"] == protocolo


class TestAtualizarScore:
    def test_atualiza_score_existente(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            resultado = csv_repository.atualizar_score("123.456.789-00", 780)
        assert resultado is True

        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            cliente = csv_repository.buscar_cliente("123.456.789-00", "1990-01-15")
        assert cliente.score == 780

    def test_cpf_inexistente(self, clientes_csv):
        from src.tools import csv_repository
        with patch.object(csv_repository, "CLIENTES_CSV", clientes_csv):
            resultado = csv_repository.atualizar_score("000.000.000-00", 500)
        assert resultado is False
