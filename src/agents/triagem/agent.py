"""Agente de Triagem — autenticação e roteamento.

Responsável por autenticar o cliente via CPF + data de nascimento
e identificar a intenção para redirecionar ao agente correto.

O roteamento usa um classificador LLM (intent_classifier.py) em vez de
keyword matching, tornando o handoff robusto a variações de linguagem natural.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage, SystemMessage

from src.config import MAX_TENTATIVAS_AUTH
from src.infrastructure.model_provider import invocar_com_fallback, normalizar_content
from src.models.state import BancoAgilState
from src.tools.csv_repository import buscar_cliente
from src.tools.intent_classifier import classificar_intencao

from .contract import contrato_consulta_financeira, corrigir_resposta
from .prompt import build_system_prompt

logger = logging.getLogger(__name__)

_INTENCOES_ENCERRAR = {"encerrar", "tchau", "sair", "até logo", "ate logo", "obrigado"}

_RE_TOOL_CALL = re.compile(
    r"^(tools\.|functions\.|<tool_call>|\{\"name\"|<function_calls>)", re.IGNORECASE
)
_RE_CODE_BLOCK = re.compile(
    r"(```[\s\S]{0,20}?\n|^\s*import\s+\w|^\s*from\s+\w+\s+import|"
    r"tool_input\s*=|^\s*\{\s*[\"'](cpf|args|name)[\"'])",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitizar(texto: str) -> str | None:
    """Retorna None se o texto parecer uma chamada de ferramenta ou código."""
    stripped = (texto or "").strip()
    if not stripped:
        logger.warning("[TRIAGEM] Resposta LLM vazia rejeitada")
        return None
    if _RE_TOOL_CALL.match(stripped):
        logger.warning("[TRIAGEM] Rejeitado (padrão tool_call): %.120s", stripped)
        return None
    if _RE_CODE_BLOCK.search(stripped):
        logger.warning("[TRIAGEM] Rejeitado (padrão código): %.120s", stripped)
        return None
    return stripped


def _invocar_llm_seguro(messages: list, fallback_msg: str, hints: list | None = None) -> str:
    msgs = messages + (hints or [])
    resposta = invocar_com_fallback(msgs)
    raw = normalizar_content(getattr(resposta, "content", None))
    logger.debug("[TRIAGEM] LLM raw: %.200s", raw)
    texto = _sanitizar(raw)
    if not texto:
        logger.warning("[TRIAGEM] Usando fallback: %s", fallback_msg)
        return fallback_msg
    return texto


def _identificar_agente(mensagem: str) -> tuple[str | None, str]:
    """Classifica a mensagem e retorna (agente_ou_None, intencao_bruta).

    A intenção bruta é propagada para o state para aparecer no staging
    de curadoria — mesmo quando é "nenhum" ou "encerrar".
    """
    intencao = classificar_intencao(mensagem)
    agente = None if intencao in ("nenhum",) else intencao
    return agente, intencao


def _extrair_cpf(texto: str) -> str | None:
    m = re.search(r"\b\d{3}[\.\-]?\d{3}[\.\-]?\d{3}[\.\-]?\d{2}\b", texto)
    return m.group(0) if m else None


def _extrair_data(texto: str) -> str | None:
    m = re.search(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b", texto)
    return m.group(0) if m else None


def no_triagem(state: BancoAgilState) -> dict:
    """Nó do grafo responsável pela triagem e autenticação.

    Contrato de saída:
      resposta_final = str  → gerou mensagem para o usuário
      resposta_final = None → apenas roteou, sem mensagem
    """
    ultima_msg = state["messages"][-1].content if state["messages"] else ""
    ultima_msg_lower = ultima_msg.lower()

    # ── Cliente já autenticado ────────────────────────────────────────────────
    if state.get("cliente_autenticado"):
        agente_atual = state.get("agente_ativo", "triagem")

        if agente_atual != "triagem":
            if any(p in ultima_msg_lower for p in _INTENCOES_ENCERRAR):
                return {"encerrado": True, "resposta_final": None, "intent_detectada": "encerrar"}
            novo_agente, intencao_bruta = _identificar_agente(ultima_msg)
            if novo_agente and novo_agente != "encerrar" and novo_agente != agente_atual:
                return {
                    "agente_ativo": novo_agente,
                    "resposta_final": None,
                    "intent_detectada": intencao_bruta,
                }
            return {"resposta_final": None, "intent_detectada": intencao_bruta}

        agente, intencao_bruta = _identificar_agente(ultima_msg)
        if agente == "encerrar":
            return {"encerrado": True, "resposta_final": None, "intent_detectada": "encerrar"}
        if agente in ("credito", "cambio", "entrevista"):
            return {
                "agente_ativo": agente,
                "resposta_final": None,
                "intent_detectada": intencao_bruta,
            }

        # Sem intenção clara: LLM responde com dados reais do cliente
        cliente = state["cliente_autenticado"]
        messages = [SystemMessage(content=build_system_prompt(cliente))] + list(state["messages"])

        contrato = contrato_consulta_financeira(cliente)

        def _invocar(hints: list | None) -> str:
            return _invocar_llm_seguro(
                messages,
                fallback_msg="Como posso ajudá-lo hoje?",
                hints=[SystemMessage(content=h["content"]) for h in (hints or [])],
            )

        texto = contrato.executar(
            invocar_fn=_invocar,
            corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente),
        )
        return {
            "messages": [AIMessage(content=texto)],
            "resposta_final": texto,
            "intent_detectada": intencao_bruta,
        }

    # ── Não autenticado: verificar se temos CPF + data ───────────────────────
    # Busca CPF e data APENAS na mensagem atual para evitar que dados errados
    # de tentativas anteriores (ainda no histórico) poluam a extração.
    cpf_detectado = _extrair_cpf(ultima_msg)
    data_detectada = _extrair_data(ultima_msg)

    # Fallback: procura nas 3 mensagens mais recentes (caso o usuário envie
    # CPF e data em mensagens separadas — cenário raro com o AuthCard).
    if not (cpf_detectado and data_detectada):
        recentes = " ".join(
            m.content for m in state["messages"][-3:] if hasattr(m, "content")
        )
        if not cpf_detectado:
            cpf_detectado = _extrair_cpf(recentes)
        if not data_detectada:
            data_detectada = _extrair_data(recentes)

    if cpf_detectado and data_detectada:
        cliente = buscar_cliente(cpf_detectado, data_detectada)
        if cliente:
            logger.info("Cliente autenticado: %s", cliente.cpf)
            # ADR-023: não carregamos mais "memórias" por CPF do Qdrant.
            # Dados do cliente são voláteis e vêm das tools (CSV).
            # `memoria_cliente` permanece no state apenas para compatibilidade
            # com código downstream que ainda lê o campo — sempre lista vazia.
            primeiro_nome = cliente.nome.split()[0] if cliente.nome else "Cliente"
            texto_boas_vindas = (
                f"Olá, {primeiro_nome}! Identidade verificada com sucesso. "
                f"Como posso ajudar você hoje? "
                f"Posso consultar seu limite de crédito, score, cotações de câmbio e mais."
            )
            return {
                "cliente_autenticado": cliente.to_dict(),
                "tentativas_auth": 0,
                "agente_ativo": "triagem",
                "memoria_cliente": [],
                "memoria_salva": False,
                "messages": [AIMessage(content=texto_boas_vindas)],
                "resposta_final": texto_boas_vindas,
            }
        else:
            tentativas = state.get("tentativas_auth", 0) + 1
            logger.warning("Falha na autenticação — tentativa %d", tentativas)

            # Mensagem determinística para evitar que o LLM alucine
            # "verificado com sucesso" ou invente nomes.
            if tentativas >= MAX_TENTATIVAS_AUTH:
                texto = (
                    "Não foi possível verificar sua identidade após múltiplas tentativas. "
                    "Por segurança, o atendimento foi encerrado. "
                    "Entre em contato com nossa central de atendimento para obter suporte."
                )
                return {
                    "messages": [AIMessage(content=texto)],
                    "tentativas_auth": tentativas,
                    "resposta_final": texto,
                    "encerrado": True,
                }

            restantes = MAX_TENTATIVAS_AUTH - tentativas
            texto = (
                f"Não consegui verificar sua identidade com os dados informados. "
                f"Por favor, verifique o CPF e a data de nascimento e tente novamente. "
                f"Você ainda tem {restantes} tentativa{'s' if restantes > 1 else ''}."
            )
            return {
                "messages": [AIMessage(content=texto)],
                "tentativas_auth": tentativas,
                "resposta_final": texto,
            }

    # ── Sem dados suficientes: LLM conduz a coleta ───────────────────────────
    messages = [SystemMessage(content=build_system_prompt())] + list(state["messages"])
    texto = _invocar_llm_seguro(
        messages,
        fallback_msg="Por favor, informe seu CPF e data de nascimento para continuar.",
    )
    return {"messages": [AIMessage(content=texto)], "resposta_final": texto}
