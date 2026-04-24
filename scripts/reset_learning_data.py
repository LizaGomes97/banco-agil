"""Utilitário de reset de dados de aprendizado do curador.

A arquitetura ativa (ADR-023) tem apenas duas coleções vetoriais:
  - banco_agil_learned_routing   (golden set — semeado por seed_patterns.py)
  - banco_agil_learned_templates (golden set — semeado por seed_patterns.py)

Este script NÃO toca nessas coleções golden. Para re-semear, use:
    python scripts/seed_patterns.py --purge

O que ele faz:

1) Por padrão (modo conservador):
   Limpa as tabelas de aprendizado em `data/banco_agil.db`:
     - memory_staging
     - curator_decisions
     - curator_lessons
     - curator_dynamic_patterns
     - curator_batch_stats
     - judge_scores

2) Com `--observability`:
   Inclui também `agent_runs` e `tool_calls` (histórico de observabilidade).

3) Com `--legacy`:
   DELETA (não recria) as coleções legadas do Qdrant que foram desativadas
   pelo ADR-023:
     - banco_agil_memoria_cliente
     - banco_agil_interacoes_curadas
     - banco_agil_feedbacks_negativos
   Use uma vez após atualizar a stack para eliminar resíduos.

Uso:
    python scripts/reset_learning_data.py                      # staging/decisões
    python scripts/reset_learning_data.py --yes                # sem confirmação
    python scripts/reset_learning_data.py --observability      # + agent_runs
    python scripts/reset_learning_data.py --legacy             # + apaga legadas do Qdrant
    python scripts/reset_learning_data.py --dry-run            # só mostra o que faria
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import QDRANT_API_KEY, QDRANT_URL  # noqa: E402
from src.infrastructure.vector_store import LEGACY_COLLECTION_NAMES  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reset")

_DB_PATH = ROOT / "data" / "banco_agil.db"

_TABELAS_APRENDIZADO = [
    "memory_staging",
    "curator_decisions",
    "curator_lessons",
    "curator_dynamic_patterns",
    "curator_batch_stats",
    "judge_scores",
]

_TABELAS_OBSERVABILIDADE = [
    "agent_runs",
    "tool_calls",
]


async def apagar_collections_legadas(
    nomes: list[str], *, dry_run: bool,
) -> dict[str, tuple[int, str]]:
    """Deleta definitivamente cada collection legada do Qdrant.

    Não recria — essas coleções não são mais usadas pelo runtime.
    Retorna {nome: (pontos_antes, status)}.
    """
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY or None,
        timeout=30,
        https=False,
    )
    resultado: dict[str, tuple[int, str]] = {}
    try:
        for nome in nomes:
            try:
                existe = await client.collection_exists(nome)
            except Exception as exc:
                logger.error("Falha ao consultar '%s': %s", nome, exc)
                resultado[nome] = (0, f"erro:{exc}")
                continue

            pontos_antes = 0
            if existe:
                try:
                    r = await client.count(collection_name=nome, exact=True)
                    pontos_antes = int(getattr(r, "count", 0) or 0)
                except Exception:
                    pass

            if not existe:
                resultado[nome] = (0, "ja_ausente")
                continue

            if dry_run:
                resultado[nome] = (pontos_antes, "seria deletada")
                continue

            try:
                await client.delete_collection(collection_name=nome)
                resultado[nome] = (pontos_antes, "deletada")
            except Exception as exc:
                logger.exception("Falha ao deletar '%s'", nome)
                resultado[nome] = (pontos_antes, f"erro:{exc}")
    finally:
        await client.close()
    return resultado


def zerar_tabelas_sqlite(
    tabelas: list[str], *, dry_run: bool,
) -> dict[str, tuple[int, str]]:
    """Deleta linhas das tabelas (mantém schema). Retorna {tabela: (linhas_antes, status)}."""
    if not _DB_PATH.exists():
        logger.warning("SQLite não encontrado em %s — nada a fazer", _DB_PATH)
        return {}
    resultado: dict[str, tuple[int, str]] = {}
    with sqlite3.connect(_DB_PATH) as conn:
        for tabela in tabelas:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {tabela}")
                antes = int(cur.fetchone()[0])
            except sqlite3.OperationalError:
                resultado[tabela] = (0, "tabela_inexistente")
                continue
            if dry_run:
                resultado[tabela] = (antes, "seria_limpa")
                continue
            conn.execute(f"DELETE FROM {tabela}")
            resultado[tabela] = (antes, "limpa")
        if not dry_run:
            conn.commit()
    return resultado


def _confirmar(mensagem: str) -> bool:
    try:
        resposta = input(f"{mensagem} [s/N]: ").strip().lower()
    except EOFError:
        return False
    return resposta in ("s", "sim", "y", "yes")


def _print_resultado(titulo: str, resultado: dict[str, tuple[int, str]]) -> None:
    if not resultado:
        return
    print(f"\n{titulo}")
    print("-" * len(titulo))
    for nome, (antes, status) in resultado.items():
        print(f"  {nome:40s} {antes:>6d} registros  ->  {status}")


async def _run(args: argparse.Namespace) -> None:
    tabelas = list(_TABELAS_APRENDIZADO)
    if args.observability:
        tabelas.extend(_TABELAS_OBSERVABILIDADE)

    print("\n=== RESET DE DADOS DE APRENDIZADO ===")
    print(f"Qdrant URL      : {QDRANT_URL}")
    print(f"SQLite          : {_DB_PATH}")
    print(f"Modo            : {'DRY-RUN' if args.dry_run else 'EXECUÇÃO REAL'}")
    print(f"SQLite tabelas  : {', '.join(tabelas)}")
    if args.legacy:
        print(f"Qdrant legado   : DELETAR {', '.join(LEGACY_COLLECTION_NAMES)}")
    else:
        print("Qdrant legado   : (não alterado — use --legacy para apagar)")

    if not args.dry_run and not args.yes:
        if not _confirmar("\nConfirmar reset?"):
            print("Abortado.")
            return

    if args.skip_sqlite:
        print("\nSQLite não foi tocado (--skip-sqlite).")
    else:
        res_sqlite = zerar_tabelas_sqlite(tabelas, dry_run=args.dry_run)
        _print_resultado("SQLite", res_sqlite)

    if args.legacy:
        res_qdrant = await apagar_collections_legadas(
            LEGACY_COLLECTION_NAMES, dry_run=args.dry_run,
        )
        _print_resultado("Qdrant (legado)", res_qdrant)

    print("\nConcluído.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zera dados de aprendizado do curador (SQLite) e, opcionalmente, "
                    "apaga coleções legadas do Qdrant.",
    )
    parser.add_argument("--yes", action="store_true", help="Não pede confirmação")
    parser.add_argument("--observability", action="store_true",
                        help="Inclui agent_runs e tool_calls")
    parser.add_argument("--legacy", action="store_true",
                        help="Apaga as coleções Qdrant legadas (ADR-023)")
    parser.add_argument("--skip-sqlite", action="store_true",
                        help="Não toca no SQLite (útil combinado com --legacy)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Só mostra o que seria feito, não altera nada")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrompido.")


if __name__ == "__main__":
    main()
