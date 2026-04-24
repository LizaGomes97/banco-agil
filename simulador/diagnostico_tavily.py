"""Diagnóstico de confiabilidade do Tavily para cotações de câmbio.

Testa múltiplas queries para USD, EUR, GBP, JPY e CAD com diferentes
formulações, medindo qual retorna valores numéricos de forma consistente.

Uso:
    python -m simulador.diagnostico_tavily
"""
from __future__ import annotations

import sys
import time
import re
import os
from dataclasses import dataclass, field
from typing import Optional

# Força UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Carrega variáveis de ambiente
from dotenv import load_dotenv
load_dotenv()

from src.tools.exchange_rate import criar_tool_cambio

# ── Regex (mesma usada no agente) ──────────────────────────────────────────────
_RE_VALOR = re.compile(
    r"""
    (?:=|é|hoje[:\s]+|atual[:\s]+|agora[:\s]+|taxa[:\s]+|\bprice\b[:\s]+|\brate\b[:\s]+|\bquote\b[:\s]+)?
    \s*
    (?:R\$\s*)?
    (\d{1,3}(?:[.,]\d{3})*[.,]\d{2,4})
    \s*
    (?:BRL|reais|real|R\$)?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Queries a testar por moeda
QUERIES_USD = [
    "cotação dólar hoje em reais",
    "dólar americano hoje preço BRL",
    "USD BRL exchange rate today",
    "dollar real exchange rate",
    "dólar hoje real brasileiro",
    "USD para BRL hoje",
    "preço dólar americano real",
    "quanto custa um dólar em reais hoje",
]

QUERIES_EUR = [
    "cotação euro hoje em reais",
    "euro real exchange rate today",
    "EUR BRL hoje",
    "euro dólar hoje",
]

QUERIES_OUTRAS = [
    ("GBP", "libra esterlina hoje em reais"),
    ("GBP", "GBP BRL exchange rate"),
    ("JPY", "iene japonês hoje em reais"),
    ("JPY", "JPY BRL exchange rate"),
    ("CAD", "dólar canadense hoje em reais"),
    ("CAD", "CAD BRL exchange rate"),
]


@dataclass
class ResultadoQuery:
    query: str
    moeda: str
    sucesso: bool
    valor_extraido: Optional[str]
    content_preview: str  # primeiros 200 chars do content
    latencia_s: float
    erro: Optional[str] = None


def extrair_valor(texto: str) -> Optional[str]:
    """Extrai o primeiro valor numérico válido (1.0–100.0 BRL)."""
    matches = _RE_VALOR.findall(texto)
    candidatos = []
    for m in matches:
        normalizado = m.replace(".", ",") if "." in m and "," not in m else m
        try:
            val = float(normalizado.replace(".", "").replace(",", "."))
            if 1.0 <= val <= 100.0:
                candidatos.append((val, normalizado))
        except ValueError:
            continue
    if not candidatos:
        return None
    _, melhor = candidatos[0]
    try:
        val = float(melhor.replace(".", "").replace(",", "."))
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return melhor


def testar_query(tool, moeda: str, query: str) -> ResultadoQuery:
    t0 = time.time()
    try:
        resultado = tool.invoke({"query": query, "topic": "finance"})
        lat = round(time.time() - t0, 2)

        resultado_str = str(resultado)
        # Extrai o campo "content" para diagnóstico
        content_match = re.search(r"'content':\s*'([^']{0,300})'", resultado_str)
        content = content_match.group(1) if content_match else resultado_str[:200]

        valor = extrair_valor(resultado_str)
        return ResultadoQuery(
            query=query,
            moeda=moeda,
            sucesso=valor is not None,
            valor_extraido=valor,
            content_preview=content[:200],
            latencia_s=lat,
        )
    except Exception as e:
        lat = round(time.time() - t0, 2)
        return ResultadoQuery(
            query=query,
            moeda=moeda,
            sucesso=False,
            valor_extraido=None,
            content_preview="",
            latencia_s=lat,
            erro=str(e)[:150],
        )


def imprimir_resultado(r: ResultadoQuery, idx: int, total: int):
    status = "✅" if r.sucesso else "❌"
    print(f"\n  {status} [{idx}/{total}] {r.moeda}: \"{r.query}\"")
    print(f"     Latência: {r.latencia_s}s")
    if r.erro:
        print(f"     Erro: {r.erro}")
    else:
        print(f"     Valor: {r.valor_extraido or '(nenhum extraído)'}")
        print(f"     Content: {r.content_preview}")


def main():
    print("=" * 70)
    print("DIAGNÓSTICO TAVILY — COTAÇÕES DE CÂMBIO")
    print("=" * 70)

    tool = criar_tool_cambio()

    resultados: list[ResultadoQuery] = []

    # ── Testa USD ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  USD — {len(QUERIES_USD)} queries")
    print(f"{'─'*60}")
    for i, query in enumerate(QUERIES_USD, 1):
        r = testar_query(tool, "USD", query)
        resultados.append(r)
        imprimir_resultado(r, i, len(QUERIES_USD))
        time.sleep(1.5)  # evitar rate limit

    # ── Testa EUR ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  EUR — {len(QUERIES_EUR)} queries")
    print(f"{'─'*60}")
    for i, query in enumerate(QUERIES_EUR, 1):
        r = testar_query(tool, "EUR", query)
        resultados.append(r)
        imprimir_resultado(r, i, len(QUERIES_EUR))
        time.sleep(1.5)

    # ── Testa outras moedas ────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Outras moedas — {len(QUERIES_OUTRAS)} queries")
    print(f"{'─'*60}")
    for i, (moeda, query) in enumerate(QUERIES_OUTRAS, 1):
        r = testar_query(tool, moeda, query)
        resultados.append(r)
        imprimir_resultado(r, i, len(QUERIES_OUTRAS))
        time.sleep(1.5)

    # ── Resumo ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("RESUMO")
    print(f"{'='*70}")

    por_moeda: dict[str, list[ResultadoQuery]] = {}
    for r in resultados:
        por_moeda.setdefault(r.moeda, []).append(r)

    melhor_por_moeda: dict[str, Optional[str]] = {}
    for moeda, rs in por_moeda.items():
        total = len(rs)
        ok = [r for r in rs if r.sucesso]
        taxa = len(ok) / total * 100
        print(f"\n  {moeda}: {len(ok)}/{total} queries retornaram valor ({taxa:.0f}%)")
        for r in ok:
            print(f"    ✅ \"{r.query}\" → {r.valor_extraido} ({r.latencia_s}s)")
        for r in rs:
            if not r.sucesso:
                print(f"    ❌ \"{r.query}\"  ({r.latencia_s}s) {r.erro or ''}")
        if ok:
            # Melhor query = mais confiável (primeira que funciona, menor latência)
            melhor = min(ok, key=lambda x: x.latencia_s)
            melhor_por_moeda[moeda] = melhor.query
            print(f"    → Melhor query: \"{melhor.query}\"")
        else:
            melhor_por_moeda[moeda] = None

    print(f"\n{'='*70}")
    print("RECOMENDAÇÕES DE QUERIES")
    print(f"{'='*70}")
    for moeda, query in melhor_por_moeda.items():
        if query:
            print(f"  {moeda}: \"{query}\"")
        else:
            print(f"  {moeda}: NENHUMA query retornou valor — investigar fonte alternativa")

    print()


if __name__ == "__main__":
    main()
