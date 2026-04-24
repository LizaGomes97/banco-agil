"""Popula o golden set no Qdrant (learned_routing, learned_templates) e SQLite (curator_lessons).

Lê `seeds/patterns.json` (fonte de verdade versionada no Git) e escreve nos stores
com source='golden'. Idempotente: chamar múltiplas vezes com o mesmo JSON produz
o mesmo estado (upsert por id determinístico).

Uso:
    python scripts/seed_patterns.py                 # popula (mantém outros golden)
    python scripts/seed_patterns.py --purge         # apaga só os source='golden' antes
    python scripts/seed_patterns.py --dry-run       # só mostra o que faria
    python scripts/seed_patterns.py --file CAMINHO  # usa outro JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.infrastructure.staging_store import (  # noqa: E402
    LESSON_SOURCE_GOLDEN,
    _DB_PATH,
    staging_store,
)
from src.infrastructure.vector_store import (  # noqa: E402
    COLLECTION_LEARNED_ROUTING,
    COLLECTION_LEARNED_TEMPLATES,
    SOURCE_GOLDEN,
    vector_store,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed")

_DEFAULT_SEED = ROOT / "seeds" / "patterns.json"


def _doc_id(prefix: str, base: str) -> str:
    """ID determinístico baseado em (prefix, base) para permitir upsert."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{prefix}:{base}"))


def _carregar_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de seed não encontrado: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("JSON raiz precisa ser um objeto.")
    return data


async def _purgar_golden_qdrant(collection: str) -> int:
    """Apaga apenas pontos com source='golden'. Retorna quantos foram removidos."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    await vector_store._ensure_collections()
    client = vector_store._get_client()
    try:
        antes = await vector_store.count(collection)
        await client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=SOURCE_GOLDEN))]
            ),
        )
        depois = await vector_store.count(collection)
        return max(0, antes - depois)
    except Exception:
        logger.exception("Falha ao purgar golden de '%s'", collection)
        return 0


def _purgar_golden_sqlite() -> int:
    if not _DB_PATH.exists():
        return 0
    with sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute("DELETE FROM curator_lessons WHERE source = ?", (LESSON_SOURCE_GOLDEN,))
        conn.commit()
        return int(cur.rowcount or 0)


async def _seed_routing(itens: list[dict], *, dry_run: bool) -> int:
    """Cada exemplo vira 1 ponto em learned_routing com intent/agente no payload."""
    count = 0
    for item in itens:
        rout_id = item.get("id") or _doc_id("rout", item.get("intent", "?"))
        intent = item["intent"]
        agente = item["agente"]
        exemplos = item.get("exemplos") or []
        nota = item.get("nota") or ""
        for idx, exemplo in enumerate(exemplos):
            doc_id = _doc_id("rout", f"{rout_id}:{idx}:{exemplo}")
            if dry_run:
                count += 1
                continue
            await vector_store.add_document(
                collection=COLLECTION_LEARNED_ROUTING,
                text=exemplo,
                metadata={
                    "source": SOURCE_GOLDEN,
                    "rout_id": rout_id,
                    "intent": intent,
                    "agente": agente,
                    "nota": nota,
                },
                doc_id=doc_id,
            )
            count += 1
    return count


async def _seed_templates(itens: list[dict], *, dry_run: bool) -> int:
    """Cada template vira 1 ponto em learned_templates. Texto embedado: situacao+esqueleto."""
    count = 0
    for item in itens:
        tmpl_id = item["id"]
        intent = item["intent"]
        agente = item["agente"]
        situacao = item.get("situacao") or ""
        esqueleto = item["esqueleto"]
        placeholders = item.get("placeholders") or []
        tool_fonte = item.get("tool_fonte")
        evitar = item.get("evitar") or []
        # Embedding usa situação + esqueleto → retrieval casa pelo contexto da pergunta
        texto_indexado = f"{situacao}\n{esqueleto}".strip()
        doc_id = _doc_id("tmpl", tmpl_id)
        if dry_run:
            count += 1
            continue
        await vector_store.add_document(
            collection=COLLECTION_LEARNED_TEMPLATES,
            text=texto_indexado,
            metadata={
                "source": SOURCE_GOLDEN,
                "tmpl_id": tmpl_id,
                "intent": intent,
                "agente": agente,
                "situacao": situacao,
                "esqueleto": esqueleto,
                "placeholders": json.dumps(placeholders, ensure_ascii=False),
                "tool_fonte": tool_fonte or "",
                "evitar": json.dumps(evitar, ensure_ascii=False),
            },
            doc_id=doc_id,
        )
        count += 1
    return count


async def _seed_licoes(itens: list[dict], *, dry_run: bool) -> int:
    count = 0
    for item in itens:
        if dry_run:
            count += 1
            continue
        await staging_store.salvar_licao_golden(
            licao_id=item["id"],
            regra=item["regra"],
            motivo=item.get("motivo"),
            aplicavel_a=item.get("aplicavel_a") or [],
            source=LESSON_SOURCE_GOLDEN,
            ativa=bool(item.get("ativa", True)),
        )
        count += 1
    return count


async def _run(args: argparse.Namespace) -> None:
    path = Path(args.file) if args.file else _DEFAULT_SEED
    data = _carregar_json(path)

    routing = data.get("routing") or []
    templates = data.get("templates") or []
    licoes = data.get("licoes") or []

    print("\n=== SEED DE GOLDEN SET ===")
    print(f"Arquivo        : {path}")
    print(f"Modo           : {'DRY-RUN' if args.dry_run else 'EXECUÇÃO REAL'}")
    print(f"Purga golden?  : {'SIM' if args.purge else 'não'}")
    print(f"Contagens JSON : routing={len(routing)}  templates={len(templates)}  licoes={len(licoes)}")

    if not args.dry_run and args.purge:
        rem_routing = await _purgar_golden_qdrant(COLLECTION_LEARNED_ROUTING)
        rem_templates = await _purgar_golden_qdrant(COLLECTION_LEARNED_TEMPLATES)
        rem_licoes = _purgar_golden_sqlite()
        print(f"Purgados       : routing={rem_routing}  templates={rem_templates}  licoes={rem_licoes}")

    n_routing = await _seed_routing(routing, dry_run=args.dry_run)
    n_templates = await _seed_templates(templates, dry_run=args.dry_run)
    n_licoes = await _seed_licoes(licoes, dry_run=args.dry_run)

    print("\nInseridos (upsert):")
    print(f"  learned_routing     : {n_routing}")
    print(f"  learned_templates   : {n_templates}")
    print(f"  curator_lessons     : {n_licoes}")

    if not args.dry_run:
        total_routing = await vector_store.count(COLLECTION_LEARNED_ROUTING)
        total_templates = await vector_store.count(COLLECTION_LEARNED_TEMPLATES)
        print("\nEstado final:")
        print(f"  {COLLECTION_LEARNED_ROUTING:35s} {total_routing} pontos")
        print(f"  {COLLECTION_LEARNED_TEMPLATES:35s} {total_templates} pontos")

    await vector_store.close()
    print("\nConcluído.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula golden set (routing/templates/licoes).")
    parser.add_argument("--file", help="Caminho alternativo para o JSON (default: seeds/patterns.json)")
    parser.add_argument("--purge", action="store_true",
                        help="Antes de inserir, apaga registros com source='golden'")
    parser.add_argument("--dry-run", action="store_true", help="Só mostra o que seria feito")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrompido.")


if __name__ == "__main__":
    main()
