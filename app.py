"""Interface Streamlit — Banco Ágil Atendimento Inteligente.

Entrypoint da aplicação. Executa com:
    streamlit run app.py
"""
from __future__ import annotations

import uuid
import logging

import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

from src.graph import get_graph
from src.tools.csv_repository import registrar_lead

logging.basicConfig(level=logging.INFO)

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Banco Ágil — Atendimento",
    page_icon="🏦",
    layout="centered",
)

# ── CSS personalizado ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    .banco-header {
        background: linear-gradient(135deg, #1a3a6b 0%, #2563eb 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .banco-header h1 { color: white; margin: 0; font-size: 1.6rem; }
    .banco-header p  { color: #bfdbfe; margin: 0.3rem 0 0; font-size: 0.9rem; }

    .status-bar {
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        margin-bottom: 1rem;
        font-size: 0.85rem;
        color: #0369a1;
    }

    .lead-card {
        background: #fefce8;
        border: 1px solid #fde047;
        border-radius: 12px;
        padding: 1.5rem;
        margin-top: 1.5rem;
    }

    .stChatMessage { border-radius: 10px; }

    .banco-footer {
        text-align: center;
        color: #94a3b8;
        font-size: 0.75rem;
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# ── Cabeçalho ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="banco-header">
    <h1>🏦 Banco Ágil</h1>
    <p>Atendimento Digital Inteligente • Disponível 24h</p>
</div>
""", unsafe_allow_html=True)

# ── Estado da sessão ──────────────────────────────────────────────────────────
_DEFAULTS = {
    "thread_id": str(uuid.uuid4()),
    "historico": [],
    "encerrado": False,
    "cliente_nome": None,
    "agente_ativo": "triagem",
    "mostrar_form_lead": False,
    "lead_enviado": False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Barra de status ───────────────────────────────────────────────────────────
_LABELS_AGENTE = {
    "triagem": "🔐 Autenticação",
    "credito": "💳 Crédito",
    "entrevista": "📋 Entrevista Financeira",
    "cambio": "💱 Câmbio",
}
status_agente = _LABELS_AGENTE.get(st.session_state.agente_ativo, "")
cliente_info = f"• {st.session_state.cliente_nome}" if st.session_state.cliente_nome else ""

st.markdown(
    f'<div class="status-bar">Área atual: <strong>{status_agente}</strong> {cliente_info}</div>',
    unsafe_allow_html=True,
)

# ── Histórico de mensagens ────────────────────────────────────────────────────
for msg in st.session_state.historico:
    role = "user" if msg["role"] == "user" else "assistant"
    with st.chat_message(role, avatar="👤" if role == "user" else "🏦"):
        st.markdown(msg["content"])

# ── Input do usuário ──────────────────────────────────────────────────────────
if st.session_state.encerrado:
    st.info("Atendimento encerrado. Inicie uma nova conversa pelo menu lateral.")

    # ── Card de lead capture pós-encerramento ─────────────────────────────────
    if not st.session_state.cliente_nome and not st.session_state.lead_enviado:
        st.markdown("""
        <div class="lead-card">
            <strong>🌟 Ainda não é cliente do Banco Ágil?</strong><br>
            <span style="color:#92400e; font-size:0.9rem;">
                Preencha o formulário abaixo e nossa equipe entrará em contato
                para abrir sua conta.
            </span>
        </div>
        """, unsafe_allow_html=True)
        st.session_state.mostrar_form_lead = True

else:
    prompt = st.chat_input("Digite sua mensagem...")

    if prompt:
        st.session_state.historico.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🏦"):
            with st.spinner("Processando..."):
                try:
                    graph = get_graph()
                    config = {"configurable": {"thread_id": st.session_state.thread_id}}

                    resultado = graph.invoke(
                        {"messages": [HumanMessage(content=prompt)]},
                        config=config,
                    )

                    msgs = resultado.get("messages", [])
                    resposta = ""
                    for m in reversed(msgs):
                        if isinstance(m, AIMessage) and m.content:
                            resposta = m.content
                            break

                    if not resposta:
                        resposta = "Como posso ajudá-lo?"

                    st.markdown(resposta)
                    st.session_state.historico.append({"role": "assistant", "content": resposta})

                    if resultado.get("encerrado"):
                        st.session_state.encerrado = True

                    if resultado.get("cliente_autenticado"):
                        nome = resultado["cliente_autenticado"].get("nome", "")
                        st.session_state.cliente_nome = nome.split()[0] if nome else None

                    if resultado.get("agente_ativo"):
                        st.session_state.agente_ativo = resultado["agente_ativo"]

                    st.rerun()

                except Exception as exc:
                    logging.error("Erro no grafo: %s", exc, exc_info=True)
                    st.error(
                        "Ocorreu um erro no atendimento. Por favor, tente novamente "
                        "ou entre em contato com nossa central."
                    )

# ── Formulário de lead capture ────────────────────────────────────────────────
if st.session_state.mostrar_form_lead and not st.session_state.lead_enviado:
    st.divider()
    st.markdown("#### 📋 Solicitar cadastro no Banco Ágil")

    with st.form("form_lead", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            lead_nome = st.text_input("Nome completo *", placeholder="Ex: João da Silva")
            lead_cpf = st.text_input("CPF *", placeholder="000.000.000-00")
        with col2:
            lead_telefone = st.text_input("Telefone / WhatsApp *", placeholder="(11) 99999-9999")
            lead_limite = st.number_input(
                "Limite de crédito desejado (R$)",
                min_value=0.0,
                max_value=100_000.0,
                step=500.0,
                value=5_000.0,
            )

        st.caption("* Campos obrigatórios")
        enviado = st.form_submit_button("✅ Enviar solicitação", use_container_width=True)

        if enviado:
            erros = []
            if not lead_nome.strip():
                erros.append("Nome é obrigatório.")
            if not lead_cpf.strip():
                erros.append("CPF é obrigatório.")
            if not lead_telefone.strip():
                erros.append("Telefone é obrigatório.")

            if erros:
                for e in erros:
                    st.warning(e)
            else:
                ok = registrar_lead(
                    nome=lead_nome,
                    cpf=lead_cpf,
                    telefone=lead_telefone,
                    limite_desejado=lead_limite,
                )
                if ok:
                    st.session_state.lead_enviado = True
                    st.rerun()
                else:
                    st.error("Erro ao salvar sua solicitação. Tente novamente.")

if st.session_state.lead_enviado:
    st.success(
        "✅ **Solicitação enviada com sucesso!**\n\n"
        "Nossa equipe analisará seu cadastro e entrará em contato em até 2 dias úteis. "
        "Obrigado pelo interesse no Banco Ágil!"
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏦 Banco Ágil")
    st.caption("Atendimento Digital Inteligente")
    st.divider()

    if st.button("🔄 Nova conversa", use_container_width=True):
        for k in _DEFAULTS:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    st.divider()
    st.markdown("**Serviços disponíveis:**")
    st.markdown("• 💳 Consulta de crédito")
    st.markdown("• 📈 Aumento de limite")
    st.markdown("• 📋 Entrevista financeira")
    st.markdown("• 💱 Cotação de câmbio")

    st.divider()

    # ── Botão de lead capture permanente na sidebar ───────────────────────────
    if not st.session_state.cliente_nome and not st.session_state.lead_enviado:
        st.markdown("**Ainda não é cliente?**")
        if st.button("🌟 Quero me tornar cliente", use_container_width=True):
            st.session_state.mostrar_form_lead = not st.session_state.mostrar_form_lead
            st.rerun()
        st.divider()

    st.caption(f"Sessão: `{st.session_state.get('thread_id', '')[:8]}...`")

# ── Rodapé ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="banco-footer">Banco Ágil © 2026 • Atendimento simulado para fins de demonstração</div>',
    unsafe_allow_html=True,
)
