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
from dataclasses import dataclass
from typing import Optional

import httpx

from .config import BACKEND_URL, TIMEOUT_SEGUNDOS, ClienteSimulado
from .logging_setup import get_logger

logger = get_logger("chat_client")


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
            ok = r.status_code == 200
            logger.debug("health check → HTTP %s | ok=%s", r.status_code, ok)
            return ok
        except Exception as exc:
            logger.warning("health check falhou: %s", exc)
            return False

    async def chat(self, mensagem: str) -> ChatResult:
        """Envia uma mensagem e retorna o resultado estruturado."""
        payload = {"message": mensagem}
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id

        msg_resumo = mensagem[:80].replace("\n", " | ")
        logger.info("→ POST /api/chat | conv=%s | msg='%s'",
                    (self.conversation_id or "nova")[:8], msg_resumo)

        inicio = time.monotonic()
        try:
            r = await self._http.post("/api/chat", json=payload)
            latencia = time.monotonic() - inicio

            if r.status_code != 200:
                logger.error(
                    "← HTTP %s em %.1fs | body='%s'",
                    r.status_code, latencia, r.text[:200],
                )
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
            authenticated = bool(data.get("authenticated"))
            encerrado = bool(data.get("encerrado"))
            reply = data.get("reply", "")

            logger.info(
                "← OK %.1fs | authenticated=%s encerrado=%s | reply='%s'",
                latencia, authenticated, encerrado, reply[:100].replace("\n", " "),
            )
            logger.debug("← reply completa: %s", reply)

            return ChatResult(
                sucesso=True,
                reply=reply,
                authenticated=authenticated,
                encerrado=encerrado,
                latencia_s=latencia,
                conversation_id=self.conversation_id or "",
                status_http=200,
            )

        except httpx.TimeoutException:
            latencia = time.monotonic() - inicio
            logger.error(
                "← TIMEOUT após %.1fs | conv=%s | msg='%s'",
                latencia, (self.conversation_id or "?")[:8], msg_resumo,
            )
            return ChatResult(
                sucesso=False,
                reply="",
                authenticated=False,
                encerrado=False,
                latencia_s=latencia,
                conversation_id=self.conversation_id or "",
                erro=f"Timeout após {latencia:.0f}s",
            )
        except Exception as exc:
            latencia = time.monotonic() - inicio
            logger.error("← ERRO inesperado em %.1fs: %s", latencia, exc, exc_info=True)
            return ChatResult(
                sucesso=False,
                reply="",
                authenticated=False,
                encerrado=False,
                latencia_s=latencia,
                conversation_id=self.conversation_id or "",
                erro=str(exc),
            )

    async def autenticar(self, cliente: ClienteSimulado, usar_data_invalida: bool = False) -> ChatResult:
        """Envia a mensagem de autenticação no formato do AuthCard."""
        data = cliente.data_invalida if usar_data_invalida else cliente.data_nascimento
        valida = not usar_data_invalida
        logger.info(
            "[AUTH] cliente='%s' cpf=%s data=%s valida=%s",
            cliente.nome, cliente.cpf, data, valida,
        )
        msg = _auth_message(cliente.cpf, data)
        return await self.chat(msg)
