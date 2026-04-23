"""
Avaliador de respostas do Banco Ágil.

Score de 0 a 10 baseado em heurísticas determinísticas — sem chamadas LLM,
para que o simulador seja rápido e não gere custo adicional.

Critérios de penalização:
    - Falha HTTP ou timeout               → score 0 (falha total)
    - Resposta vazia ou muito curta       → -4
    - must_contain não satisfeito         → -2 por campo ausente
    - must_not_contain violado            → -3 por ocorrência (bugs críticos)
    - Latência > 15s                      → -1
    - Latência > 30s                      → -2
    - Resposta genérica/erro padrão       → -1
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .chat_client import ChatResult
from .question_bank import QuestionItem

# Frases que indicam que o agente não conseguiu processar a request
_FRASES_GENERICAS = [
    "não consegui processar",
    "tente novamente",
    "ocorreu um erro interno",
    "desculpe, houve um problema",
]

# Padrões que nunca devem aparecer numa resposta ao cliente
_PADROES_CRITICOS = [
    r"tools\.\w+\(",          # chamada de tool exposta: tools.buscar_cliente(
    r"def \w+\(",              # código Python
    r"import \w+",             # import Python
    r"from \w+ import",        # from Python
    r"\bTraceback\b",          # stack trace
    r"especialista\b",         # transferência revelada
    r"transferir.*?(você|vc)", # handoff revelado
]
_RE_CRITICOS = re.compile("|".join(_PADROES_CRITICOS), re.IGNORECASE)


@dataclass
class EvaluationResult:
    # Identidade
    pergunta: str
    categoria: str
    cliente_nome: str

    # Resultado
    score: float = 0.0         # 0–10
    problemas: List[str] = field(default_factory=list)
    pontos_fortes: List[str] = field(default_factory=list)

    # Dados brutos
    reply: str = ""
    latencia_s: float = 0.0
    authenticated: bool = False
    encerrado: bool = False
    erro_http: str = ""

    def passou(self) -> bool:
        return self.score >= 7.0

    def to_dict(self) -> dict:
        return {
            "pergunta": self.pergunta,
            "categoria": self.categoria,
            "cliente": self.cliente_nome,
            "score": self.score,
            "passou": self.passou(),
            "problemas": self.problemas,
            "pontos_fortes": self.pontos_fortes,
            "latencia_s": round(self.latencia_s, 2),
            "authenticated": self.authenticated,
            "encerrado": self.encerrado,
            "reply_preview": self.reply[:200] if self.reply else "",
            "erro_http": self.erro_http,
        }


def avaliar(
    result: ChatResult,
    item: QuestionItem,
    cliente_nome: str,
) -> EvaluationResult:
    """Avalia uma interação e retorna um EvaluationResult com score 0–10."""

    ev = EvaluationResult(
        pergunta=item.pergunta[:120],
        categoria=item.categoria,
        cliente_nome=cliente_nome,
        reply=result.reply,
        latencia_s=result.latencia_s,
        authenticated=result.authenticated,
        encerrado=result.encerrado,
        erro_http=result.erro,
    )

    # Falha total de rede / HTTP
    if not result.sucesso:
        ev.score = 0.0
        ev.problemas.append(f"Falha de comunicação: {result.erro or f'HTTP {result.status_http}'}")
        return ev

    score = 10.0
    reply_lower = result.reply.lower()

    # Resposta vazia ou muito curta
    if not result.reply or len(result.reply.strip()) < 20:
        score -= 4.0
        ev.problemas.append("Resposta vazia ou muito curta (< 20 chars)")
    else:
        ev.pontos_fortes.append("Resposta com conteúdo")

    # Padrões críticos (código, tool calls, handoff) — penalização pesada
    critico = _RE_CRITICOS.search(result.reply)
    if critico:
        score -= 3.0
        ev.problemas.append(f"Padrão crítico detectado na resposta: '{critico.group()[:60]}'")

    # must_contain
    for substring in item.must_contain:
        if substring.lower() not in reply_lower:
            score -= 2.0
            ev.problemas.append(f"Conteúdo esperado ausente: '{substring}'")

    # must_not_contain
    for substring in item.must_not_contain:
        if substring.lower() in reply_lower:
            score -= 3.0
            ev.problemas.append(f"Conteúdo proibido na resposta: '{substring}'")

    # Frases genéricas de erro (indica que o agente falhou silenciosamente)
    for frase in _FRASES_GENERICAS:
        if frase in reply_lower:
            score -= 1.0
            ev.problemas.append(f"Resposta genérica de falha detectada: '{frase}'")
            break

    # Latência — Gemini free tier pode fazer retries até ~62s em 429
    if result.latencia_s > 75:
        score -= 2.0
        ev.problemas.append(f"Latência muito alta: {result.latencia_s:.1f}s (> 75s)")
    elif result.latencia_s > 30:
        score -= 1.0
        ev.problemas.append(f"Latência alta: {result.latencia_s:.1f}s (> 30s — possível rate limit)")
    else:
        ev.pontos_fortes.append(f"Latência ok: {result.latencia_s:.1f}s")

    ev.score = max(0.0, min(10.0, score))
    return ev


def avaliar_auth(
    result: ChatResult,
    cliente_nome: str,
    esperava_sucesso: bool,
    tentativa: int = 1,
) -> EvaluationResult:
    """Avaliação especializada para o fluxo de autenticação."""
    ev = EvaluationResult(
        pergunta=f"[AUTH tentativa {tentativa}]",
        categoria="autenticacao",
        cliente_nome=cliente_nome,
        reply=result.reply,
        latencia_s=result.latencia_s,
        authenticated=result.authenticated,
        encerrado=result.encerrado,
        erro_http=result.erro,
    )

    if not result.sucesso:
        ev.score = 0.0
        ev.problemas.append(f"Falha HTTP no login: {result.erro}")
        return ev

    score = 10.0

    if esperava_sucesso:
        if result.authenticated:
            ev.pontos_fortes.append("Autenticação bem-sucedida")
        else:
            score -= 5.0
            ev.problemas.append("Esperava authenticated=True mas recebeu False")
    else:
        if not result.authenticated:
            ev.pontos_fortes.append("Negou acesso corretamente com credenciais inválidas")
        else:
            score -= 5.0
            ev.problemas.append("Autenticou com credenciais INVÁLIDAS — falha de segurança!")

    # Padrões críticos na resposta de auth
    if _RE_CRITICOS.search(result.reply):
        score -= 3.0
        ev.problemas.append("Código ou tool call exposto na resposta de auth")

    ev.score = max(0.0, min(10.0, score))
    return ev
