"""
Cria as collections do Qdrant para o projeto Banco Ágil.

banco_agil_memoria_cliente  — memória semântica por sessão/cliente
banco_agil_base_conhecimento — FAQ e regras do banco (RAG)
"""

import urllib.request
import json

API_KEY = "XM6PAjWTjM44oBRG6M5YV9k3MPhEhFTThOm8VE7N"
BASE = "http://localhost:6333"
DIMENSION = 3072  # gemini-embedding-001


def criar_collection(nome: str, descricao: str):
    payload = json.dumps({
        "vectors": {
            "size": DIMENSION,
            "distance": "Cosine",
        }
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
    ("banco_agil_memoria_cliente",   "Memória semântica de interações por cliente"),
    ("banco_agil_base_conhecimento", "FAQ, regras e produtos do Banco Ágil"),
]

print("Criando collections no Qdrant...")
for nome, desc in collections:
    criar_collection(nome, desc)

# Verifica
req = urllib.request.Request(f"{BASE}/collections", headers={"api-key": API_KEY})
with urllib.request.urlopen(req, timeout=5) as r:
    data = json.loads(r.read())
nomes = [c["name"] for c in data["result"]["collections"]]
print(f"\nQdrant atual: {nomes}")
