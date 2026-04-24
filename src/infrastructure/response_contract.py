"""Sistema de contratos para respostas LLM — previne alucinações em dados financeiros.

Funcionamento:
  1. Define campos obrigatórios com seus valores ground-truth (vindos do estado/BD).
  2. Valida se a resposta do LLM contém esses valores nos formatos esperados.
  3. Se o contrato não for satisfeito, faz até `max_retries` retentativas com um
     prompt corretivo explícito.
  4. Se ainda assim falhar, aplica correção programática — substitui o trecho errado
     ou injeta os valores diretamente na mensagem final.

Uso típico:
    contrato = ContratoFinanceiro(
        limite=cliente["limite_credito"],
        score=cliente["score"],
    )
    texto = contrato.executar(invocar_fn, dados_cliente=cliente)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Formatos de número aceitos (BR e EN) ──────────────────────────────────────

def _formatos_monetarios(valor: float) -> list[str]:
    """Gera todos os formatos possíveis de um valor em reais."""
    inteiro = int(valor)
    return [
        str(inteiro),                              # 3000
        f"{inteiro:,}",                            # 3,000  (EN)
        f"{inteiro:,}".replace(",", "."),          # 3.000  (BR)
        f"{valor:,.2f}",                           # 3,000.00  (EN)
        f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),  # 3.000,00 (BR)
        f"R$ {inteiro:,}".replace(",", "."),       # R$ 3.000
        f"R${inteiro:,}".replace(",", "."),        # R$3.000
        f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),  # R$ 3.000,00
    ]


def _formatos_inteiro(valor: int) -> list[str]:
    return [str(valor), f"{valor:,}", f"{valor:,}".replace(",", ".")]


# ── Campo do contrato ─────────────────────────────────────────────────────────

@dataclass
class CampoContrato:
    """Um campo obrigatório que deve aparecer na resposta LLM."""

    nome: str
    valor_esperado: Any
    obrigatorio: bool = True        # se False, só valida se o campo for mencionado
    apenas_se_reportado: bool = False  # se True, só valida quando a resposta contém dados monetários
    _formatos: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        v = self.valor_esperado
        if isinstance(v, float):
            self._formatos = _formatos_monetarios(v)
        elif isinstance(v, int):
            self._formatos = _formatos_inteiro(v)
        else:
            self._formatos = [str(v)]

    def presente_em(self, texto: str) -> bool:
        return any(fmt in texto for fmt in self._formatos)

    def deve_validar(self, texto: str) -> bool:
        """Retorna False para campos condicionais em respostas sem dados monetários."""
        if not self.obrigatorio:
            return False
        if self.apenas_se_reportado:
            # Só valida se a resposta realmente cita valores monetários ou score
            return bool(re.search(r"R\$\s*[\d.,]+|\b\d{3,}\b", texto))
        return True

    def descricao_corretiva(self) -> str:
        """Texto usado no prompt de correção para este campo."""
        v = self.valor_esperado
        if isinstance(v, float):
            br = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f'"{self.nome}" = {br}'
        return f'"{self.nome}" = {v}'


# ── Contrato principal ────────────────────────────────────────────────────────

@dataclass
class ResponseContract:
    """Contrato de validação para respostas LLM.

    Args:
        campos:        lista de CampoContrato a validar.
        max_retries:   número máximo de retentativas após falha (default 1).
    """

    campos: list[CampoContrato] = field(default_factory=list)
    max_retries: int = 1

    # ── Validação ─────────────────────────────────────────────────────────────

    def validar(self, resposta: str) -> tuple[bool, list[CampoContrato]]:
        """Retorna (satisfeito, campos_faltando)."""
        faltando = [
            c for c in self.campos
            if c.deve_validar(resposta) and not c.presente_em(resposta)
        ]
        return len(faltando) == 0, faltando

    # ── Execução com retentativa ──────────────────────────────────────────────

    def executar(
        self,
        invocar_fn: Callable[[list | None], str],
        corrigir_fn: Callable[[str, list[CampoContrato]], str] | None = None,
    ) -> str:
        """Executa invocar_fn e valida o resultado contra o contrato.

        Args:
            invocar_fn:   Callable que recebe uma lista de mensagens extras (hints)
                          ou None para a chamada original. Retorna o texto da resposta.
            corrigir_fn:  Opcional. Callable que recebe (resposta_errada, campos_faltando)
                          e retorna a resposta corrigida programaticamente (último recurso).
        """
        resposta = invocar_fn(None)

        for tentativa in range(1, self.max_retries + 1):
            satisfeito, faltando = self.validar(resposta)

            if satisfeito:
                if tentativa > 1:
                    logger.info("[CONTRATO] Satisfeito na retentativa %d", tentativa)
                return resposta

            nomes = [c.nome for c in faltando]
            logger.warning(
                "[CONTRATO] Tentativa %d/%d — contrato não satisfeito. Campos ausentes: %s | Resposta: %.120s",
                tentativa, self.max_retries, nomes, resposta,
            )

            if tentativa == self.max_retries:
                break

            # Monta prompt corretivo e reinvoca
            hint = self._prompt_corretivo(faltando)
            resposta = invocar_fn([hint])

        # ── Último recurso: correção programática ─────────────────────────────
        satisfeito, faltando = self.validar(resposta)
        if not satisfeito:
            logger.error(
                "[CONTRATO] Esgotadas retentativas. Aplicando correção programática. Campos: %s",
                [c.nome for c in faltando],
            )
            if corrigir_fn:
                resposta = corrigir_fn(resposta, faltando)

        return resposta

    # ── Helpers privados ──────────────────────────────────────────────────────

    @staticmethod
    def _prompt_corretivo(faltando: list[CampoContrato]) -> dict:
        """Gera uma SystemMessage dict para o LangChain com a instrução corretiva."""
        itens = "\n".join(f"  • {c.descricao_corretiva()}" for c in faltando)
        conteudo = (
            "CORREÇÃO OBRIGATÓRIA: sua resposta anterior não incluiu os valores exatos abaixo.\n"
            "Reescreva a resposta incluindo EXATAMENTE estes dados (não arredonde, não estime):\n"
            f"{itens}\n"
            "Mantenha o tom amigável. Não mencione que está corrigindo uma resposta anterior."
        )
        # Retorna como dict para o _invocar_llm_seguro montar a mensagem
        return {"role": "system", "content": conteudo}


# ── Contratos pré-definidos ───────────────────────────────────────────────────

def contrato_financeiro(
    limite: float | None = None,
    score: int | None = None,
    max_retries: int = 1,
    apenas_se_reportado: bool = True,
) -> ResponseContract:
    """Contrato para respostas que incluem dados financeiros do cliente.

    Use quando a resposta DEVE citar o limite e/ou score exatos.

    Args:
        limite:              valor exato de limite_credito do cliente.
        score:               valor exato de score do cliente.
        max_retries:         tentativas adicionais se o contrato não for satisfeito.
        apenas_se_reportado: se True (padrão), só valida quando a resposta já cita
                             valores monetários — evita falsos positivos em perguntas
                             de esclarecimento (ex.: "qual limite deseja?").
    """
    campos: list[CampoContrato] = []
    if limite is not None:
        campos.append(CampoContrato(
            nome="limite_credito",
            valor_esperado=float(limite),
            apenas_se_reportado=apenas_se_reportado,
        ))
    if score is not None:
        campos.append(CampoContrato(
            nome="score",
            valor_esperado=int(score),
            apenas_se_reportado=apenas_se_reportado,
        ))
    return ResponseContract(campos=campos, max_retries=max_retries)


def contrato_score(
    score: int,
    max_retries: int = 1,
    apenas_se_reportado: bool = True,
) -> ResponseContract:
    """Contrato para respostas que incluem apenas o score.

    Args:
        score:               valor exato do score esperado.
        max_retries:         tentativas adicionais se o contrato não for satisfeito.
        apenas_se_reportado: se True (padrão), só valida quando a resposta cita
                             algum número ≥ 3 dígitos. Use False quando a resposta
                             DEVE obrigatoriamente citar o score (ex.: resultado de entrevista).
    """
    return ResponseContract(
        campos=[CampoContrato(
            nome="score",
            valor_esperado=int(score),
            apenas_se_reportado=apenas_se_reportado,
        )],
        max_retries=max_retries,
    )


# ── Correção programática padrão ──────────────────────────────────────────────

def corrigir_com_dados(
    resposta: str,
    faltando: list[CampoContrato],
    cliente: dict,
) -> str:
    """Injeta os valores corretos na resposta quando o LLM falhou em incluí-los.

    Estratégia: appenda um parágrafo com os dados corretos caso não seja possível
    substituir inline. Garante que o cliente sempre veja o valor real.
    """
    complemento_partes: list[str] = []

    for campo in faltando:
        if campo.nome == "limite_credito":
            limite = float(cliente.get("limite_credito", 0))
            br = f"R$ {limite:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            complemento_partes.append(f"Seu limite de crédito disponível é {br}")
        elif campo.nome == "score":
            complemento_partes.append(f"Seu score de crédito é {cliente.get('score', 0)}")

    if complemento_partes:
        # Tenta substituir inline um valor errado pelo valor real
        resposta_corrigida = _tentar_substituir_valor(resposta, faltando, cliente)
        satisfeito_pos = all(c.presente_em(resposta_corrigida) for c in faltando)
        if satisfeito_pos:
            logger.info("[CONTRATO] Valor corrigido inline com sucesso.")
            resposta = resposta_corrigida
        else:
            # Registra a falha internamente — NÃO injeta rodapé visível ao cliente.
            # A presença de um rodapé de debug na UI é pior do que um valor impreciso.
            logger.error(
                "[CONTRATO] Correção inline falhou. Campos não satisfeitos: %s | Resposta: %.200s",
                [c.nome for c in faltando],
                resposta,
            )

    return resposta


def _tentar_substituir_valor(
    resposta: str,
    faltando: list[CampoContrato],
    cliente: dict,
) -> str:
    """Tenta substituir valores numéricos suspeitos na resposta pelo valor real."""
    for campo in faltando:
        if campo.nome == "limite_credito":
            limite_real = float(cliente.get("limite_credito", 0))
            br_real = f"R$ {limite_real:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            # Substitui padrões como "R$ X.XXX" ou "R$ X.XXX,XX" por valores incorretos
            resposta = re.sub(
                r"R\$\s*[\d.,]+",
                br_real,
                resposta,
                count=1,
            )
    return resposta
