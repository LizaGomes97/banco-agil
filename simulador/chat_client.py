"""
Cliente HTTP assíncrono para a API do Banco Ágil.

Responsabilidades:
    - Verificar saúde da API (/api/health)
    - Gerenciar uma sessão de conversa (conversation_id)
    - Enviar a mensagem de autenticação e mensagens subsequentes
    - Retornar ChatResult com metadados para o avaliador
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .config import BACKEND_URL, TIMEOUT_SEGUNDOS, ClienteSimulado


def _auth_message(cpf: str, data: str) -> str:
    """Replica o formato exato gerado pelo buildAuthMessage do frontend."""
    return f"CPF: {cpf}\nData de nascimento: {data}"


@dataclass
class ChatResult:
    sucesso: bool
    reply: str
    authenticated: bool
    encerrado: bool
    latencia_s: float
    conversation_id: str
    status_http: int = 200
    erro: str = ""


class BancoAgilClient:
    """Representa uma sessão de chat com o agente.

    Uso típico:
        async with BancoAgilClient() as client:
            auth = await client.autenticar(cliente)
            resp = await client.chat("qual meu limite?")
    """

    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None
        self.conversation_id: Optional[str] = None

    async def __aenter__(self) -> "BancoAgilClient":
        self._http = httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=TIMEOUT_SEGUNDOS,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._http:
            await self._http.aclose()

    async def health(self) -> bool:
        """Verifica se a API está respondendo."""
        try:
            r = await self._http.get("/api/health")
            return r.status_code == 200
        except Exception:
            return False

    async def chat(self, mensagem: str) -> ChatResult:
        """Envia uma mensagem e retorna o resultado estruturado."""
        payload = {"message": mensagem}
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id

        inicio = time.monotonic()
        try:
            r = await self._http.post("/api/chat", json=payload)
            latencia = time.monotonic() - inicio

            if r.status_code != 200:
                return ChatResult(
                    sucesso=False,
                    reply="",
                    authenticated=False,
                    encerrado=False,
                    latencia_s=latencia,
                    conversation_id=self.conversation_id or "",
                    status_http=r.status_code,
                    erro=f"HTTP {r.status_code}: {r.text[:200]}",
                )

            data = r.json()
            self.conversation_id = data.get("conversation_id", self.conversation_id)
            return ChatResult(
                sucesso=True,
                reply=data.get("reply", ""),
                authenticated=bool(data.get("authenticated")),
                encerrado=bool(data.get("encerrado")),
                latencia_s=latencia,
                conversation_id=self.conversation_id or "",
                status_http=200,
            )

        except httpx.TimeoutException:
            return ChatResult(
                sucesso=False,
                reply="",
                authenticated=False,
                encerrado=False,
                latencia_s=TIMEOUT_SEGUNDOS,
                conversation_id=self.conversation_id or "",
                erro=f"Timeout após {TIMEOUT_SEGUNDOS}s",
            )
        except Exception as exc:
            return ChatResult(
                sucesso=False,
                reply="",
                authenticated=False,
                encerrado=False,
                latencia_s=time.monotonic() - inicio,
                conversation_id=self.conversation_id or "",
                erro=str(exc),
            )

    async def autenticar(self, cliente: ClienteSimulado, usar_data_invalida: bool = False) -> ChatResult:
        """Envia a mensagem de autenticação no formato do AuthCard."""
        data = cliente.data_invalida if usar_data_invalida else cliente.data_nascimento
        msg = _auth_message(cliente.cpf, data)
        return await self.chat(msg)
