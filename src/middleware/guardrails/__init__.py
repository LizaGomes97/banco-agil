"""
Agregador de guardrails do Banco Ágil.

Ponto único de importação para o api/main.py:

    from src.middleware.guardrails import input_runner, output_runner

As listas definem a ORDEM de execução dentro de cada fase.
Guardrails mais severos devem vir primeiro dentro de sua fase.

Para adicionar um novo guardrail:
    1. Crie o arquivo em src/middleware/guardrails/
    2. Implemente GuardrailBase com o método run()
    3. Instancie e adicione à lista correta abaixo
"""

from ._base import GuardrailResult, GuardrailRunner, Severidade
from .escopo_bancario import EscopoBancarioGuardrail
from .pii_output import PiiOutputGuardrail
from .prompt_injection import PromptInjectionGuardrail
from .tamanho_input import TamanhoInputGuardrail
from .tom_agressivo import TomAgressivoGuardrail

# ---------------------------------------------------------------------------
# Input: executado ANTES do graph.invoke(), na requisição do usuário
# ---------------------------------------------------------------------------
_INPUT_GUARDRAILS = [
    PromptInjectionGuardrail(),   # CRITICO + ALTO + MEDIO
    EscopoBancarioGuardrail(),    # ALTO + MEDIO
    TamanhoInputGuardrail(),      # MEDIO
]

# ---------------------------------------------------------------------------
# Output: executado DEPOIS do graph.invoke(), antes de entregar ao cliente
# ---------------------------------------------------------------------------
_OUTPUT_GUARDRAILS = [
    PiiOutputGuardrail(),         # CRITICO + ALTO
    TomAgressivoGuardrail(),      # MEDIO
]

input_runner = GuardrailRunner(_INPUT_GUARDRAILS)
output_runner = GuardrailRunner(_OUTPUT_GUARDRAILS)

__all__ = [
    "input_runner",
    "output_runner",
    "GuardrailResult",
    "Severidade",
]
