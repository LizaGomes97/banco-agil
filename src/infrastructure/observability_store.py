"""Observabilidade — rastreamento persistente de execuções do agente.

Porta do padrão de MS_GeoMap/backend/observability/obs_store.py, adaptado
para SQLite (mesmo DB do staging, em data/banco_agil.db).

Tabelas:
  - agent_runs:  cada /api/chat vira 1 run (duração, modelo, status)
  - tool_calls:  cada tool chamada dentro de um run (nome, args, duração, ok?)

Retenção: 30 dias (limpeza manual via `limpar_runs_antigos()`).

Privacidade: NÃO armazena a mensagem bruta do usuário — armazena a rota
(tools + params estruturados). CPF aparece no payload estruturado quando
vier como argumento de tool, mas não livre no input.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import ROOT_DIR

logger = logging.getLogger(__name__)

_DB_PATH: Path = ROOT_DIR / "data" / "banco_agil.db"

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_BLOCKED_INPUT = "blocked_input"

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id            TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL,
        cpf           TEXT,
        started_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ended_at      TEXT,
        duration_ms   INTEGER,
        agent_name    TEXT,
        intent        TEXT,
        total_tools   INTEGER NOT NULL DEFAULT 0,
        status        TEXT NOT NULL DEFAULT 'running'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_cpf ON agent_runs(cpf, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs(started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id            TEXT PRIMARY KEY,
        run_id        TEXT NOT NULL,
        tool_name     TEXT NOT NULL,
        input_summary TEXT,
        success       INTEGER NOT NULL,
        duration_ms   INTEGER,
        called_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name)",
]


class ObservabilityStore:
    """Store síncrono — usado pelo hot path do FastAPI."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._init_lock = threading.Lock()
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                for stmt in _DDL_STATEMENTS:
                    conn.execute(stmt)
                conn.commit()
            self._initialized = True
            logger.info("ObservabilityStore inicializado em %s", self._db_path)

    @contextmanager
    def _conexao(self):
        self._ensure_init()
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── API de escrita ──────────────────────────────────────────────────

    def iniciar_run(self, *, session_id: str, cpf: str | None = None) -> str:
        """Cria um run com status='running' e retorna o id."""
        run_id = str(uuid.uuid4())
        try:
            with self._conexao() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_runs (id, session_id, cpf, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, session_id, cpf, STATUS_RUNNING),
                )
        except Exception:
            logger.exception("Falha ao iniciar run (ignorando)")
            return ""
        return run_id

    def atualizar_cpf_run(self, run_id: str, cpf: str) -> None:
        """Atualiza o CPF associado a um run (usado quando auth acontece durante o turno)."""
        if not run_id or not cpf:
            return
        try:
            with self._conexao() as conn:
                conn.execute(
                    "UPDATE agent_runs SET cpf = ? WHERE id = ?",
                    (cpf, run_id),
                )
        except Exception:
            logger.exception("Falha ao atualizar CPF do run")

    def finalizar_run(
        self,
        run_id: str,
        *,
        agent_name: str | None = None,
        intent: str | None = None,
        total_tools: int = 0,
        duration_ms: int = 0,
        status: str = STATUS_COMPLETED,
    ) -> None:
        if not run_id:
            return
        try:
            with self._conexao() as conn:
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET ended_at = CURRENT_TIMESTAMP,
                        agent_name = ?, intent = ?,
                        total_tools = ?, duration_ms = ?, status = ?
                    WHERE id = ?
                    """,
                    (agent_name, intent, total_tools, duration_ms, status, run_id),
                )
        except Exception:
            logger.exception("Falha ao finalizar run (ignorando)")

    def registrar_tool_call(
        self,
        run_id: str,
        *,
        tool_name: str,
        tool_input: dict | None = None,
        success: bool = True,
        duration_ms: int = 0,
    ) -> None:
        if not run_id:
            return
        try:
            resumo = (
                json.dumps(tool_input, ensure_ascii=False, default=str)[:1000]
                if tool_input else None
            )
            with self._conexao() as conn:
                conn.execute(
                    """
                    INSERT INTO tool_calls
                      (id, run_id, tool_name, input_summary, success, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), run_id, tool_name, resumo,
                        1 if success else 0, duration_ms,
                    ),
                )
        except Exception:
            logger.exception("Falha ao registrar tool_call (ignorando)")

    # ── API de leitura (dashboard) ─────────────────────────────────────

    def listar_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._conexao() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, session_id, cpf, started_at, ended_at, duration_ms,
                           agent_name, intent, total_tools, status
                    FROM agent_runs
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("Falha ao listar runs")
            return []

    def listar_tool_calls(self, run_id: str) -> list[dict[str, Any]]:
        try:
            with self._conexao() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, tool_name, input_summary, success, duration_ms, called_at
                    FROM tool_calls
                    WHERE run_id = ?
                    ORDER BY called_at ASC
                    """,
                    (run_id,),
                ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["success"] = bool(d["success"])
                if d.get("input_summary"):
                    try:
                        d["input_summary"] = json.loads(d["input_summary"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                out.append(d)
            return out
        except Exception:
            logger.exception("Falha ao listar tool_calls")
            return []

    def limpar_runs_antigos(self, dias: int = 30) -> int:
        """Remove runs (e tool_calls via CASCADE) mais antigos que N dias."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        try:
            with self._conexao() as conn:
                cur = conn.execute(
                    "DELETE FROM agent_runs WHERE started_at < ?", (cutoff,),
                )
                # SQLite não suporta FK CASCADE por padrão sem PRAGMA; limpamos manual.
                conn.execute(
                    """
                    DELETE FROM tool_calls
                    WHERE run_id NOT IN (SELECT id FROM agent_runs)
                    """,
                )
                return cur.rowcount or 0
        except Exception:
            logger.exception("Falha ao limpar runs antigos")
            return 0


observability_store = ObservabilityStore()
