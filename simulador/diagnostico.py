"""
Diagnóstico de conectividade e quota do Gemini.

Testa 3 coisas isoladas para diferenciar os problemas:
    1. Chave Gemini está válida e respondendo?
    2. Quantas chamadas LLM o grafo faz por mensagem?
    3. Cache do classificador está funcionando?

Uso:
    python -m simulador.diagnostico
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Força UTF-8 no stdout para suportar caracteres como → em terminais Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _sep(titulo: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {titulo}")
    print("=" * 60)


def teste_1_chave_gemini() -> bool:
    """Chama o Gemini direto, sem o agente, para validar a chave."""
    _sep("TESTE 1: Chave Gemini responde?")

    try:
        from langchain_core.messages import HumanMessage
        from src.config import GEMINI_API_KEY, GEMINI_MODEL
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception as exc:
        print(f"[ERRO] Falha ao importar: {exc}")
        return False

    if not GEMINI_API_KEY:
        print("[ERRO] GEMINI_API_KEY não configurada")
        return False

    print(f"Modelo: {GEMINI_MODEL}")
    print(f"Chave: ...{GEMINI_API_KEY[-8:]}")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=0,
        google_api_key=GEMINI_API_KEY,
    )

    inicio = time.monotonic()
    try:
        r = llm.invoke([HumanMessage(content="Diga apenas 'OK'")])
        lat = time.monotonic() - inicio
        print(f"[OK] Resposta em {lat:.1f}s: '{r.content[:50]}'")
        return True
    except Exception as exc:
        lat = time.monotonic() - inicio
        erro = str(exc)
        print(f"[FALHA] em {lat:.1f}s: {erro[:200]}")
        if "429" in erro or "Resource exhausted" in erro:
            print("\n>>> Chave está funcionando MAS quota esgotada.")
            print(">>> Gemini free tier: 15 RPM + 1500 RPD (requisições por dia).")
            print(">>> Aguarde 1 min (rate) ou até amanhã (daily) para resetar.")
        elif "API_KEY_INVALID" in erro or "403" in erro:
            print("\n>>> Chave Gemini inválida ou sem permissão.")
        return False


def teste_2_contar_chamadas_llm() -> None:
    """Intercepta invocar_com_fallback para contar chamadas por mensagem."""
    _sep("TESTE 2: Quantas chamadas LLM o grafo faz por mensagem?")

    try:
        from langchain_core.messages import HumanMessage
        from src import infrastructure
        from src.graph import get_graph
    except Exception as exc:
        print(f"[ERRO] Falha ao importar: {exc}")
        return

    # Monkey-patch para contar
    from src.infrastructure import model_provider
    original = model_provider.invocar_com_fallback
    contador = {"total": 0, "tiers": []}

    def contador_wrapper(*args, **kwargs):
        contador["total"] += 1
        tier = kwargs.get("tier", "fast")
        contador["tiers"].append(tier)
        return original(*args, **kwargs)

    model_provider.invocar_com_fallback = contador_wrapper

    # Intercepta também o classificador
    from src.tools import intent_classifier
    original_classificar = intent_classifier.classificar_intencao
    classificador_count = {"total": 0}

    def classificador_wrapper(*args, **kwargs):
        classificador_count["total"] += 1
        return original_classificar(*args, **kwargs)

    intent_classifier.classificar_intencao = classificador_wrapper

    try:
        graph = get_graph()
        print("\nEnviando mensagem de autenticação...")
        inicio = time.monotonic()
        graph.invoke(
            {"messages": [HumanMessage(content="CPF: 123.456.789-00\nData de nascimento: 15/01/1990")]},
            config={"configurable": {"thread_id": "diag-auth"}},
        )
        lat = time.monotonic() - inicio
        print(f"  → {contador['total']} chamadas LLM via invocar_com_fallback")
        print(f"  → {classificador_count['total']} chamadas ao classificador")
        print(f"  → tiers usados: {contador['tiers']}")
        print(f"  → tempo total: {lat:.1f}s")

        # Reset contador para teste 2
        contador["total"] = 0
        contador["tiers"] = []
        classificador_count["total"] = 0

        time.sleep(5)  # respeita rate limit
        print("\nEnviando pergunta: 'qual meu limite?'")
        inicio = time.monotonic()
        graph.invoke(
            {"messages": [HumanMessage(content="qual meu limite?")]},
            config={"configurable": {"thread_id": "diag-auth"}},
        )
        lat = time.monotonic() - inicio
        print(f"  → {contador['total']} chamadas LLM via invocar_com_fallback")
        print(f"  → {classificador_count['total']} chamadas ao classificador")
        print(f"  → tiers usados: {contador['tiers']}")
        print(f"  → tempo total: {lat:.1f}s")

    except Exception as exc:
        print(f"[ERRO] {exc}")
    finally:
        model_provider.invocar_com_fallback = original
        intent_classifier.classificar_intencao = original_classificar


def teste_3_cache_classificador() -> None:
    """Testa se o cache do classificador está reduzindo chamadas."""
    _sep("TESTE 3: Cache do classificador está ativo?")

    try:
        from src.tools.intent_classifier import classificar_intencao
        import src.tools.intent_classifier as ic
    except Exception as exc:
        print(f"[ERRO] Falha ao importar: {exc}")
        return

    # Verifica se existe cache
    tem_cache = hasattr(ic, "_cache") or any("cache" in a.lower() for a in dir(ic))
    print(f"Cache no módulo: {tem_cache}")

    pergunta = "qual meu limite de crédito?"

    t1 = time.monotonic()
    r1 = classificar_intencao(pergunta)
    lat1 = time.monotonic() - t1

    t2 = time.monotonic()
    r2 = classificar_intencao(pergunta)
    lat2 = time.monotonic() - t2

    print(f"\nPrimeira chamada:  {lat1:.2f}s → {r1}")
    print(f"Segunda chamada:   {lat2:.2f}s → {r2}")
    print(f"Speedup: {lat1/lat2:.1f}x" if lat2 > 0 else "  (imediato)")
    if lat2 < 0.1:
        print("[OK] Cache funcionando — 2a chamada foi imediata")
    else:
        print("[AVISO] Cache não parece estar ativo — 2a chamada custou tempo")


def main():
    # Carregar .env
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
            print(f"[OK] .env carregado de {env_file}")
        except ImportError:
            print("[AVISO] python-dotenv não instalado, lendo env do sistema")

    ok1 = teste_1_chave_gemini()
    if not ok1:
        print("\n\n>>> Teste 1 falhou. Corrija antes de prosseguir.")
        return

    teste_3_cache_classificador()
    teste_2_contar_chamadas_llm()


if __name__ == "__main__":
    main()
