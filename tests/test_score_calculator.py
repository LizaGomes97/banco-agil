"""Testes unitários para o cálculo determinístico de score de crédito.

Estes testes verificam que a fórmula implementada corresponde
exatamente aos pesos definidos no desafio técnico.
"""
import pytest
from src.tools.score_calculator import calcular_score_credito, score_aprovado


class TestCalcularScoreCredito:
    def test_perfil_ideal(self):
        """Renda alta + formal + sem dependentes + sem dívidas = score máximo."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 30000.0,
            "tipo_emprego": "formal",
            "num_dependentes": 0,
            "tem_dividas": "não",
        })
        assert resultado["score"] == 900 + 300 + 100 + 100  # 1400 → cap renda 900
        assert resultado["aprovado"] is True

    def test_perfil_desempregado_com_dividas(self):
        """Renda zero + desempregado + dívidas = score baixo."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 0.0,
            "tipo_emprego": "desempregado",
            "num_dependentes": 0,
            "tem_dividas": "sim",
        })
        assert resultado["score"] == 0 + 0 + 100 + (-100)  # 0
        assert resultado["aprovado"] is False

    def test_perfil_autonomo_dois_dependentes(self):
        """Autônomo com renda média, 2 dependentes, sem dívidas."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 4000.0,
            "tipo_emprego": "autônomo",
            "num_dependentes": 2,
            "tem_dividas": "não",
        })
        pts_renda = min(4000 / 1000 * 30, 900)   # 120
        esperado = round(pts_renda + 200 + 60 + 100)  # 480
        assert resultado["score"] == esperado
        assert resultado["aprovado"] is False  # 480 < 500

    def test_cap_renda(self):
        """Renda muito alta não deve ultrapassar o cap de 900 pontos."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 100_000.0,
            "tipo_emprego": "formal",
            "num_dependentes": 0,
            "tem_dividas": "não",
        })
        assert resultado["detalhamento"]["renda"] == 900

    def test_tres_ou_mais_dependentes(self):
        """Três ou mais dependentes usa o peso padrão de 30."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 5000.0,
            "tipo_emprego": "formal",
            "num_dependentes": 3,
            "tem_dividas": "não",
        })
        assert resultado["detalhamento"]["dependentes"] == 30

    def test_sem_acento_autonomo(self):
        """Aceita 'autonomo' sem acento."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 3000.0,
            "tipo_emprego": "autonomo",
            "num_dependentes": 1,
            "tem_dividas": "nao",
        })
        assert resultado["detalhamento"]["emprego"] == 200
        assert resultado["detalhamento"]["dividas"] == 100

    def test_retorna_detalhamento_completo(self):
        """O resultado deve conter todos os campos esperados."""
        resultado = calcular_score_credito.invoke({
            "renda_mensal": 2000.0,
            "tipo_emprego": "formal",
            "num_dependentes": 1,
            "tem_dividas": "sim",
        })
        assert "score" in resultado
        assert "aprovado" in resultado
        assert "detalhamento" in resultado
        assert set(resultado["detalhamento"].keys()) == {"renda", "emprego", "dependentes", "dividas"}


class TestScoreAprovado:
    def test_score_exatamente_no_limiar(self):
        assert score_aprovado(500) is True

    def test_score_abaixo_do_limiar(self):
        assert score_aprovado(499) is False

    def test_score_acima_do_limiar(self):
        assert score_aprovado(750) is True

    def test_score_zero(self):
        assert score_aprovado(0) is False
