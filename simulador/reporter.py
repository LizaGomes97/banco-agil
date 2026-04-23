"""
Geração de relatórios de simulação do Banco Ágil.

Salva em simulador/reports/:
    - AAAA-MM-DD_HHMMSS_resumo.md   → relatório legível por humanos
    - AAAA-MM-DD_HHMMSS_sessao.json → dados completos para análise
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .config import REPORTS_DIR
from .evaluator import EvaluationResult


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _estatisticas(resultados: List[EvaluationResult]) -> dict:
    if not resultados:
        return {}

    scores = [r.score for r in resultados]
    por_categoria: Dict[str, List[float]] = {}
    falhas_criticas: List[str] = []

    for r in resultados:
        por_categoria.setdefault(r.categoria, []).append(r.score)
        for p in r.problemas:
            if "crítico" in p.lower() or "segurança" in p.lower() or "INVÁLIDAS" in p:
                falhas_criticas.append(f"[{r.categoria}] {r.cliente_nome}: {p}")

    media_por_categoria = {
        cat: round(sum(v) / len(v), 2)
        for cat, v in por_categoria.items()
    }

    passaram = sum(1 for r in resultados if r.passou())

    return {
        "total": len(resultados),
        "passaram": passaram,
        "falharam": len(resultados) - passaram,
        "taxa_sucesso_pct": round(passaram / len(resultados) * 100, 1),
        "score_medio": round(sum(scores) / len(scores), 2),
        "score_min": min(scores),
        "score_max": max(scores),
        "latencia_media_s": round(
            sum(r.latencia_s for r in resultados) / len(resultados), 2
        ),
        "por_categoria": media_por_categoria,
        "falhas_criticas": falhas_criticas,
    }


def save_json(resultados: List[EvaluationResult], session_id: str) -> Path:
    """Salva os dados completos da sessão em JSON."""
    reports_path = Path(REPORTS_DIR)
    reports_path.mkdir(parents=True, exist_ok=True)

    ts = _timestamp()
    path = reports_path / f"{ts}_sessao.json"

    payload = {
        "session_id": session_id,
        "gerado_em": datetime.now().isoformat(),
        "estatisticas": _estatisticas(resultados),
        "interacoes": [r.to_dict() for r in resultados],
    }

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_markdown(resultados: List[EvaluationResult], session_id: str) -> Path:
    """Salva um resumo legível em Markdown."""
    reports_path = Path(REPORTS_DIR)
    reports_path.mkdir(parents=True, exist_ok=True)

    ts = _timestamp()
    path = reports_path / f"{ts}_resumo.md"
    stats = _estatisticas(resultados)

    linhas = [
        f"# Relatório de Simulação — Banco Ágil",
        f"",
        f"**Sessão:** `{session_id}`  ",
        f"**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"",
        f"## Resumo Geral",
        f"",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Total de interações | {stats.get('total', 0)} |",
        f"| Passaram (score ≥ 7) | {stats.get('passaram', 0)} |",
        f"| Falharam | {stats.get('falharam', 0)} |",
        f"| Taxa de sucesso | {stats.get('taxa_sucesso_pct', 0)}% |",
        f"| Score médio | {stats.get('score_medio', 0)}/10 |",
        f"| Latência média | {stats.get('latencia_media_s', 0)}s |",
        f"",
    ]

    # Score por categoria
    por_cat = stats.get("por_categoria", {})
    if por_cat:
        linhas += [
            "## Score por Categoria",
            "",
            "| Categoria | Score Médio |",
            "|-----------|-------------|",
        ]
        for cat, score in sorted(por_cat.items(), key=lambda x: x[1]):
            emoji = "✅" if score >= 7 else "⚠️" if score >= 5 else "❌"
            linhas.append(f"| {cat} | {emoji} {score}/10 |")
        linhas.append("")

    # Falhas críticas
    falhas = stats.get("falhas_criticas", [])
    if falhas:
        linhas += [
            "## ⚠️ Falhas Críticas",
            "",
            "> Estes problemas exigem correção antes do deploy.",
            "",
        ]
        for f in falhas:
            linhas.append(f"- {f}")
        linhas.append("")

    # Detalhes por interação (só as que falharam)
    falhas_det = [r for r in resultados if not r.passou()]
    if falhas_det:
        linhas += [
            "## Interações com Falha (score < 7)",
            "",
        ]
        for r in falhas_det:
            linhas += [
                f"### [{r.categoria}] {r.cliente_nome} — score {r.score}/10",
                f"**Pergunta:** {r.pergunta}",
                f"**Resposta (prévia):** {r.reply[:300]}",
                f"**Latência:** {r.latencia_s:.1f}s",
                f"**Problemas:**",
            ]
            for p in r.problemas:
                linhas.append(f"  - {p}")
            linhas.append("")

    path.write_text("\n".join(linhas), encoding="utf-8")
    return path
