"""Cria as collections ativas do Qdrant para o projeto Banco Ágil.

Coleções criadas (ver ADR-023 — arquitetura de memória de padrões golden):
  - banco_agil_learned_routing    → exemplos de intenção (input -> intent/agente)
  - banco_agil_learned_templates  → esqueletos de resposta com placeholders

O `VectorStore` também cria essas coleções automaticamente no primeiro
acesso, então este script é opcional — útil apenas para provisionar
previamente antes de rodar o seed (`python scripts/seed_patterns.py`).

Coleções legadas (memoria_cliente, interacoes_curadas, feedbacks_negativos)
foram removidas da arquitetura; use `scripts/reset_learning_data.py --legacy`
para limpar resíduos.
"""

import json
import urllib.request

from src.config import QDRANT_API_KEY, QDRANT_EMBEDDING_DIMENSION, QDRANT_URL

API_KEY = QDRANT_API_KEY
BASE = QDRANT_URL.rstrip("/")
DIMENSION = QDRANT_EMBEDDING_DIMENSION


def criar_collection(nome: str, descricao: str) -> None:
    payload = json.dumps({
        "vectors": {"size": DIMENSION, "distance": "Cosine"},
    }).encode()

    req = urllib.request.Request(
        f"{BASE}/collections/{nome}",
        data=payload,
        method="PUT",
        headers={"api-key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            if resp.get("result"):
                print(f"  CRIADA: {nome}  ({descricao})")
            else:
                print(f"  AVISO {nome}: {resp}")
    except Exception as e:
        print(f"  ERRO {nome}: {e}")


collections = [
    ("banco_agil_learned_routing",   "Roteamento: input -> intent/agente (ADR-023)"),
    ("banco_agil_learned_templates", "Templates de resposta com placeholders (ADR-023)"),
]

print("Criando collections no Qdrant...")
for nome, desc in collections:
    criar_collection(nome, desc)

req = urllib.request.Request(f"{BASE}/collections", headers={"api-key": API_KEY})
with urllib.request.urlopen(req, timeout=5) as r:
    data = json.loads(r.read())
nomes = [c["name"] for c in data["result"]["collections"]]
print(f"\nQdrant atual: {nomes}")
