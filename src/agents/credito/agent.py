"""Agente de Crédito — pipeline Flash→Pro para decisão de limite.

Fase 1 (Flash): modelo rápido conduz a conversa e chama as tools de
    verificação, registro e atualização de limite.

Fase 2 (Pro): acionado apenas quando houve tool calls. Sintetiza a resposta
    final com tom empático e profissional.

Além do fluxo normal, este nó trata dois estados especiais:
    1. `aguardando_confirmacao == "entrevista"` — a resposta anterior ofereceu
       a entrevista de crédito. A próxima mensagem do cliente é sim/não.
    2. `pedido_pendente is not None` — o cliente voltou da entrevista com
       novo score. Se a mensagem confirmar, re-disparamos a elegibilidade
       usando o valor original sem perguntar novamente.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from src.infrastructure.few_shot import buscar_exemplos_curados
from src.infrastructure.model_provider import invocar_com_fallback, normalizar_content
from src.models.state import BancoAgilState
from src.tools.credit_tools import (
    atualizar_limite_cliente,
    registrar_pedido_aumento,
    verificar_elegibilidade_aumento,
)

from .contract import contrato_flash_direto, contrato_sintese_pro, corrigir_resposta
from .prompt import build_flash_prompt, build_pro_prompt

logger = logging.getLogger(__name__)

_TOOLS_FLASH = [
    verificar_elegibilidade_aumento,
    registrar_pedido_aumento,
    atualizar_limite_cliente,
]
_TOOL_MAP = {
    "verificar_elegibilidade_aumento": verificar_elegibilidade_aumento,
    "registrar_pedido_aumento": registrar_pedido_aumento,
    "atualizar_limite_cliente": atualizar_limite_cliente,
}

_RE_HANDOFF = re.compile(
    r"(transferi|direcionar|especialista|setor|área de atendimento|aguarde)",
    re.IGNORECASE,
)
_RE_ENCERRAR = re.compile(r"\b(encerrar|tchau|sair|até logo|ate logo)\b", re.IGNORECASE)
_RE_AFIRMATIVO = re.compile(
    r"\b(sim|quero|gostaria|pode\s+(ser|sim)|claro|aceito|vamos|"
    r"com\s+certeza|por\s+favor|\bok\b|beleza|uhum|isso)\b",
    re.IGNORECASE,
)
_RE_NEGATIVO = re.compile(
    r"\b(n[ãa]o|prefiro\s+n[ãa]o|depois|mais\s+tarde|agora\s+n[ãa]o|"
    r"dispensar?|deixa\s+(pra\s+)?l[áa])\b",
    re.IGNORECASE,
)


def _interpretar_sim_nao(texto: str) -> str | None:
    """Heurística leve: retorna 'sim', 'nao' ou None (ambíguo)."""
    if not texto:
        return None
    if _RE_AFIRMATIVO.search(texto) and not _RE_NEGATIVO.search(texto):
        return "sim"
    if _RE_NEGATIVO.search(texto):
        return "nao"
    return None


def _tratar_aguardando_entrevista(state: BancoAgilState, ultima_msg: str) -> dict | None:
    """Lida com a resposta do cliente à oferta de entrevista.

    Retorna um dict com updates do state ou None se a mensagem for ambígua
    (nesse caso o fluxo continua no pipeline Flash→Pro normal).
    """
    decisao = _interpretar_sim_nao(ultima_msg)
    cliente = state.get("cliente_autenticado", {})
    nome = cliente.get("nome", "").split()[0]

    if decisao == "sim":
        logger.info("[CREDITO] Cliente aceitou entrevista — roteando")
        texto = (
            f"Perfeito, {nome}. Vou fazer algumas perguntas rápidas sobre seu "
            "perfil financeiro para reavaliarmos seu score."
        )
        return {
            "messages": [AIMessage(content=texto)],
            "agente_ativo": "entrevista",
            "aguardando_confirmacao": None,
            "resposta_final": texto,
        }

    if decisao == "nao":
        logger.info("[CREDITO] Cliente recusou entrevista")
        texto = (
            f"Tudo bem, {nome}. Caso queira, posso te ajudar com outras consultas "
            "como cotação de câmbio ou informações do seu cadastro. "
            "Se preferir, posso encerrar o atendimento — é só me avisar."
        )
        return {
            "messages": [AIMessage(content=texto)],
            "agente_ativo": "triagem",
            "aguardando_confirmacao": None,
            "pedido_pendente": None,
            "resposta_final": texto,
        }

    return None


def _tratar_retomada_pendente(
    state: BancoAgilState, ultima_msg: str
) -> tuple[dict | None, dict | None]:
    """Processa o retorno da entrevista com `pedido_pendente` preenchido.

    Retorna (updates, pedido_normalizado):
      - updates: None se deve seguir fluxo normal do crédito (cliente confirmou
        e queremos re-rodar o pipeline usando o valor do pedido_pendente).
      - updates: dict de state updates se o cliente recusou ou está ambíguo.
      - pedido_normalizado: valor confirmado para uso no fluxo normal.
    """
    pedido = state.get("pedido_pendente") or {}
    decisao = _interpretar_sim_nao(ultima_msg)
    cliente = state.get("cliente_autenticado", {})
    nome = cliente.get("nome", "").split()[0]

    if decisao == "nao":
        texto = (
            f"Sem problemas, {nome}. Se mudar de ideia, é só me avisar. "
            "Posso ajudar com cotação de câmbio ou outra consulta?"
        )
        return (
            {
                "messages": [AIMessage(content=texto)],
                "agente_ativo": "triagem",
                "aguardando_confirmacao": None,
                "pedido_pendente": None,
                "resposta_final": texto,
            },
            None,
        )

    if decisao == "sim":
        return None, pedido

    # Ambíguo: pergunta direto sem perder o pedido.
    valor = float(pedido.get("limite_solicitado", 0))
    texto = (
        f"{nome}, só para confirmar: você gostaria de tentar novamente "
        f"o aumento para R$ {valor:,.2f}? (sim / não)"
    )
    return (
        {
            "messages": [AIMessage(content=texto)],
            "aguardando_confirmacao": "retomada",
            "resposta_final": texto,
        },
        None,
    )


def no_credito(state: BancoAgilState) -> dict:
    """Nó do grafo para o Agente de Crédito (pipeline Flash→Pro).

    Trata três cenários antes do pipeline normal:
      1. Encerramento explícito do cliente.
      2. `aguardando_confirmacao == "entrevista"` → interpreta sim/não.
      3. `pedido_pendente` presente → interpreta sim/não para retomar.
    """
    cliente = state.get("cliente_autenticado", {})
    ultima_msg = state["messages"][-1].content if state["messages"] else ""

    if _RE_ENCERRAR.search(ultima_msg or ""):
        return {"encerrado": True, "resposta_final": None}

    aguardando = state.get("aguardando_confirmacao")

    if aguardando == "entrevista":
        resposta = _tratar_aguardando_entrevista(state, ultima_msg)
        if resposta is not None:
            return resposta
        # Ambíguo: reconfirma a oferta
        nome = cliente.get("nome", "").split()[0]
        texto = (
            f"{nome}, quer fazer uma entrevista rápida para atualizar seu "
            "score e tentarmos novamente? (sim / não)"
        )
        return {
            "messages": [AIMessage(content=texto)],
            "aguardando_confirmacao": "entrevista",
            "resposta_final": texto,
        }

    pedido_pendente = state.get("pedido_pendente")
    pedido_confirmado: dict | None = None

    if pedido_pendente:
        updates, confirmado = _tratar_retomada_pendente(state, ultima_msg)
        if updates is not None:
            return updates
        pedido_confirmado = confirmado

    # ── Pipeline Flash→Pro ────────────────────────────────────────────────────
    limite = float(cliente.get("limite_credito", 0))
    score = int(cliente.get("score", 0))
    memorias = state.get("memoria_cliente") or []

    exemplos_curados = buscar_exemplos_curados(ultima_msg, intent="credito")

    system_content = build_flash_prompt(cliente, memorias, exemplos_curados)

    # Se há pedido confirmado (cliente voltou da entrevista e disse sim),
    # injetamos instrução determinística para que o Flash dispare a verificação
    # sem perguntar o valor novamente.
    if pedido_confirmado:
        valor = float(pedido_confirmado.get("limite_solicitado", 0))
        system_content += (
            "\n\n## Retomada de solicitação\n"
            f"O cliente já havia solicitado um aumento para R$ {valor:,.2f} "
            "antes da entrevista de crédito. O novo score já está no contexto. "
            "Chame `verificar_elegibilidade_aumento` diretamente com este valor "
            "e prossiga o fluxo normal (registrar pedido + atualizar limite se aprovado). "
            "Não pergunte o valor novamente."
        )

    messages = [SystemMessage(content=system_content)] + list(state["messages"])

    # ── Fase 1: Flash ─────────────────────────────────────────────────────────
    try:
        resposta_flash = invocar_com_fallback(messages, tier="fast", tools=_TOOLS_FLASH)
    except Exception as exc:
        logger.error("[CREDITO] Falha no Flash: %s", exc)
        fallback = "Entendido! Como posso te ajudar com seu crédito hoje?"
        return {"messages": [AIMessage(content=fallback)], "resposta_final": fallback}

    # Sem tool calls: Flash responde diretamente
    if not getattr(resposta_flash, "tool_calls", None):
        texto = normalizar_content(resposta_flash.content).strip()

        if _RE_HANDOFF.search(texto):
            logger.warning("[CREDITO] Flash gerou handoff — descartado: %.100s", texto)
            nome = cliente.get("nome", "").split()[0]
            texto = (
                f"{nome}, seu limite atual é R$ {limite:,.2f} e seu score é {score}. "
                f"Posso ajudar com mais alguma coisa?"
            )
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

        # Guarda de alucinação: LLM disse que registrou algo mas não chamou tool.
        _RE_REGISTRO_FALSO = re.compile(
            r"(registr(ei|amos|ado)|anot(ei|amos)|solicitação\s+(foi\s+)?registrada|pedido\s+recebido)",
            re.IGNORECASE,
        )
        if _RE_REGISTRO_FALSO.search(texto):
            logger.warning("[CREDITO] Alucinação de registro detectada: %.150s", texto)
            nome = cliente.get("nome", "").split()[0]
            texto = (
                f"{nome}, para solicitar um aumento de limite preciso saber: "
                "qual valor você gostaria de solicitar?"
            )
            return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

        contrato = contrato_flash_direto(cliente)

        def _invocar_flash_hint(hints: list | None) -> str:
            if not hints:
                return texto
            try:
                msgs_hint = messages + [SystemMessage(content=hints[0]["content"])]
                r = invocar_com_fallback(msgs_hint, tier="fast", tools=_TOOLS_FLASH)
                return normalizar_content(r.content).strip()
            except Exception:
                return texto

        texto = contrato.executar(
            invocar_fn=_invocar_flash_hint,
            corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente),
        )

        return {"messages": [AIMessage(content=texto)], "resposta_final": texto}

    # ── Loop ReAct: Flash pode chamar tools em sequência ─────────────────────
    # O Gemini chama UMA tool por vez e espera o resultado antes de decidir a
    # próxima. Sem este loop, só a primeira tool executaria (ex.: verificar
    # elegibilidade) e registrar+atualizar_limite seriam perdidas.
    MAX_ITER_REACT = 4

    todas_tool_msgs: list[ToolMessage] = []
    todas_ai_msgs: list = [resposta_flash]
    elegibilidade: dict | None = None
    pedido_registrado: dict | None = None
    limite_atualizado_via_tool = False
    historico_pipeline = list(messages)
    resposta_atual = resposta_flash

    iteracao = 0
    while getattr(resposta_atual, "tool_calls", None) and iteracao < MAX_ITER_REACT:
        iteracao += 1

        tool_msgs_rodada: list[ToolMessage] = []
        for tc in resposta_atual.tool_calls:
            nome_tool = tc.get("name", "")
            tool_fn = _TOOL_MAP.get(nome_tool)
            try:
                if tool_fn is None:
                    resultado = {"erro": f"Tool '{nome_tool}' não reconhecida."}
                else:
                    resultado = tool_fn.invoke(tc["args"])
                logger.info(
                    "[CREDITO] (iter %d) Tool '%s' executada: %s",
                    iteracao, nome_tool, resultado,
                )
                if nome_tool == "verificar_elegibilidade_aumento":
                    elegibilidade = resultado
                elif nome_tool == "registrar_pedido_aumento":
                    pedido_registrado = resultado
                elif nome_tool == "atualizar_limite_cliente":
                    if isinstance(resultado, dict) and resultado.get("sucesso"):
                        limite_atualizado_via_tool = True
            except Exception as exc:
                logger.error("[CREDITO] Erro na tool '%s': %s", nome_tool, exc)
                resultado = {"erro": str(exc)}
            tool_msgs_rodada.append(
                ToolMessage(content=str(resultado), tool_call_id=tc["id"])
            )

        todas_tool_msgs.extend(tool_msgs_rodada)
        historico_pipeline = (
            historico_pipeline + [resposta_atual] + tool_msgs_rodada
        )

        # Re-invoca o Flash com o resultado para ele decidir a próxima ação
        try:
            resposta_atual = invocar_com_fallback(
                historico_pipeline, tier="fast", tools=_TOOLS_FLASH
            )
            todas_ai_msgs.append(resposta_atual)
        except Exception as exc:
            logger.error("[CREDITO] Falha ao continuar Flash no loop ReAct: %s", exc)
            break

    if iteracao >= MAX_ITER_REACT and getattr(resposta_atual, "tool_calls", None):
        logger.warning(
            "[CREDITO] Loop ReAct atingiu MAX_ITER=%d — encerrando sem executar últimas tool_calls",
            MAX_ITER_REACT,
        )

    logger.info(
        "[CREDITO] Loop ReAct concluído | iterações=%d | tools_executadas=%d",
        iteracao, len(todas_tool_msgs),
    )

    # ── Pós-processamento determinístico ──────────────────────────────────────
    # Garante consistência entre a tabela score_limite, o CSV de solicitações
    # e o CSV de clientes, mesmo que o Flash não tenha chamado todas as tools.
    updates_pos: dict = {}

    if elegibilidade is not None:
        aprovado = bool(elegibilidade.get("elegivel"))
        valor_sol = float(elegibilidade.get("novo_limite_solicitado", 0))
        cpf = cliente.get("cpf", "")

        # Se aprovou e o Flash esqueceu de registrar o pedido, registramos.
        if aprovado and pedido_registrado is None and cpf and valor_sol > 0:
            logger.warning(
                "[CREDITO] Flash aprovou mas não chamou registrar_pedido — "
                "executando pós-hoc"
            )
            try:
                pedido_registrado = registrar_pedido_aumento.invoke({
                    "cpf": cpf,
                    "limite_atual": float(elegibilidade.get("limite_atual", limite)),
                    "novo_limite_solicitado": valor_sol,
                    "status": "aprovado",
                })
                logger.info("[CREDITO] Pedido registrado pós-hoc: %s", pedido_registrado)
            except Exception as exc:
                logger.error("[CREDITO] Erro ao registrar pedido pós-hoc: %s", exc)

        # Se não aprovou e o Flash também esqueceu, registramos como rejeitado.
        if not aprovado and pedido_registrado is None and cpf and valor_sol > 0:
            logger.warning(
                "[CREDITO] Flash rejeitou mas não chamou registrar_pedido — "
                "executando pós-hoc"
            )
            try:
                pedido_registrado = registrar_pedido_aumento.invoke({
                    "cpf": cpf,
                    "limite_atual": float(elegibilidade.get("limite_atual", limite)),
                    "novo_limite_solicitado": valor_sol,
                    "status": "rejeitado",
                })
                logger.info("[CREDITO] Pedido rejeitado registrado pós-hoc: %s", pedido_registrado)
            except Exception as exc:
                logger.error("[CREDITO] Erro ao registrar pedido pós-hoc: %s", exc)

        if aprovado and pedido_registrado and pedido_registrado.get("sucesso"):
            # Se o Flash esqueceu de atualizar o limite, chamamos nós.
            if not limite_atualizado_via_tool and cpf and valor_sol > 0:
                try:
                    res_upd = atualizar_limite_cliente.invoke(
                        {"cpf": cpf, "novo_limite": valor_sol}
                    )
                    if isinstance(res_upd, dict) and res_upd.get("sucesso"):
                        limite_atualizado_via_tool = True
                    logger.info("[CREDITO] Limite atualizado pós-hoc: %s", res_upd)
                except Exception as exc:
                    logger.error("[CREDITO] Erro ao atualizar limite pós-hoc: %s", exc)

            updates_pos["cliente_autenticado"] = {
                **cliente,
                "limite_credito": valor_sol,
            }
            updates_pos["pedido_pendente"] = None
            updates_pos["aguardando_confirmacao"] = None

        elif not aprovado:
            updates_pos["pedido_pendente"] = {
                "limite_solicitado": valor_sol,
                "limite_atual": float(elegibilidade.get("limite_atual", limite)),
            }
            updates_pos["aguardando_confirmacao"] = "entrevista"

    # ── Fase 2: Pro — síntese da decisão ──────────────────────────────────────
    # Inclui a última resposta do Flash (pode ter texto final sem tool_calls ou
    # conter tool_calls que excederam o MAX_ITER do loop ReAct).
    historico_para_pro = historico_pipeline + [resposta_atual]
    # Mensagens novas introduzidas nesta rodada (AIs + ToolMessages).
    # Essas são as que precisamos devolver ao state do LangGraph para manter
    # consistência do histórico (AIMessage com tool_calls precisa ter os
    # ToolMessages correspondentes).
    extra_msgs = historico_para_pro[len(messages):]

    system_pro_content = build_pro_prompt(cliente, memorias, exemplos_curados)

    # Se houve rejeição, instruímos o Pro a oferecer a entrevista SEM despachar
    if elegibilidade is not None and not elegibilidade.get("elegivel"):
        system_pro_content += (
            "\n\n## Instrução específica\n"
            "A solicitação foi REPROVADA por score insuficiente. Você deve:\n"
            "1. Informar ao cliente o motivo (linguagem acessível, sem jargão).\n"
            "2. OFERECER uma entrevista rápida para reavaliar o score.\n"
            "3. Perguntar explicitamente se o cliente deseja fazer a entrevista (sim/não).\n"
            "4. NÃO diga 'vou iniciar a entrevista' — apenas ofereça e aguarde a resposta."
        )

    system_pro = SystemMessage(content=system_pro_content)

    try:
        resposta_pro = invocar_com_fallback([system_pro] + historico_para_pro, tier="pro")
        texto_pro = normalizar_content(resposta_pro.content).strip()
        msgs_retorno = list(extra_msgs) + [resposta_pro]
    except Exception as exc:
        logger.error("[CREDITO] Falha no Pro: %s", exc)
        texto_pro = ""
        msgs_retorno = list(extra_msgs)

    # ── Fallback determinístico quando o Pro não produz texto ────────────────
    # Gemini às vezes devolve content vazio mesmo com sucesso; sem isso a UI
    # receberia string vazia e cairia no histórico de mensagens como fallback.
    if not texto_pro:
        nome = cliente.get("nome", "").split()[0]
        if (
            elegibilidade is not None
            and elegibilidade.get("elegivel")
            and pedido_registrado
            and pedido_registrado.get("sucesso")
        ):
            novo_lim = float(elegibilidade.get("novo_limite_solicitado", 0))
            protocolo = pedido_registrado.get("protocolo", "")
            trecho_proto = f" (protocolo: {protocolo})" if protocolo else ""
            texto_pro = (
                f"Parabéns, {nome}! Sua solicitação foi aprovada. "
                f"Seu novo limite de crédito é R$ {novo_lim:,.2f}{trecho_proto} "
                "e já está disponível para uso."
            )
        elif elegibilidade is not None and not elegibilidade.get("elegivel"):
            teto = float(elegibilidade.get("limite_maximo_permitido", 0))
            valor_sol = float(elegibilidade.get("novo_limite_solicitado", 0))
            texto_pro = (
                f"{nome}, infelizmente seu score atual permite um limite máximo de "
                f"R$ {teto:,.2f}, abaixo do valor solicitado (R$ {valor_sol:,.2f}). "
                "Posso te convidar para uma entrevista rápida que pode atualizar "
                "seu score. Gostaria de fazer? (sim / não)"
            )
        else:
            texto_pro = (
                f"{nome}, processamos sua solicitação. "
                "Em breve você receberá a confirmação."
            )
        logger.warning(
            "[CREDITO] Pro retornou vazio — aplicando fallback determinístico"
        )
        msgs_retorno = list(extra_msgs) + [AIMessage(content=texto_pro)]

    # ── Contrato: usa o limite aprovado em caso de aprovação ─────────────────
    # Sem isso, o contrato validaria contra o limite antigo e rejeitaria a
    # resposta correta do Pro que menciona o novo valor aprovado.
    cliente_para_contrato = dict(cliente)
    if (
        elegibilidade is not None
        and elegibilidade.get("elegivel")
        and pedido_registrado
        and pedido_registrado.get("sucesso")
    ):
        cliente_para_contrato["limite_credito"] = float(
            elegibilidade.get("novo_limite_solicitado", cliente.get("limite_credito", 0))
        )

    contrato_pro = contrato_sintese_pro(cliente_para_contrato)

    def _invocar_pro_hint(hints: list | None) -> str:
        if not hints:
            return texto_pro
        try:
            msgs_hint = [system_pro] + historico_para_pro + [SystemMessage(content=hints[0]["content"])]
            r = invocar_com_fallback(msgs_hint, tier="pro")
            hint_texto = normalizar_content(r.content).strip()
            return hint_texto or texto_pro
        except Exception:
            return texto_pro

    texto_pro = contrato_pro.executar(
        invocar_fn=_invocar_pro_hint,
        corrigir_fn=lambda r, f: corrigir_resposta(r, f, cliente_para_contrato),
    )

    logger.info(
        "[CREDITO] Pipeline Flash→Pro concluído | cpf=...%s | len_resposta=%d",
        str(cliente.get("cpf", ""))[-4:],
        len(texto_pro or ""),
    )

    return {
        "messages": msgs_retorno,
        "resposta_final": texto_pro,
        **updates_pos,
    }
