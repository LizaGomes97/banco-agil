from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Cliente:
    cpf: str
    nome: str
    data_nascimento: str
    limite_credito: float
    score: int

    def to_dict(self) -> dict:
        return {
            "cpf": self.cpf,
            "nome": self.nome,
            "data_nascimento": self.data_nascimento,
            "limite_credito": self.limite_credito,
            "score": self.score,
        }


@dataclass
class SolicitacaoAumento:
    cpf: str
    limite_atual: float
    limite_solicitado: float
    status: Literal["aprovado", "reprovado", "pendente"] = "pendente"
    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:8])
    criado_em: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cpf": self.cpf,
            "limite_atual": self.limite_atual,
            "limite_solicitado": self.limite_solicitado,
            "status": self.status,
            "criado_em": self.criado_em,
        }
