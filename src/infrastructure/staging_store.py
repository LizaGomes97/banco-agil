"""Staging store — persistência relacional para curadoria de memória.

Adaptado de MS_GeoMap/backend/memory/postgres_store.py.
Implementação com SQLite (via aiosqlite) para zero-config em dev e case.
O schema é compatível com Postgres — trocar o driver é a única mudança.

Tabelas gerenciadas (ver ADR-023):
  - memory_staging:           fila de turnos candidatos à curadoria
  - curator_lessons:          Camada 1 — discrepâncias Flash vs Pro
  - curator_dynamic_patterns: Camada 2 — padrões recorrentes descobertos
  - curator_batch_stats:      Camada 3 — auto-calibração por taxa

Todos os acessos vão por este módulo — ninguém toca o DB diretamente.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from pathlib import Path

import aiosqlite

from src.config import ROOT_DIR

logger = logging.getLogger(__name__)

_DB_PATH: Path = ROOT_DIR / "data" / "banco_agil.db"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_GROUPED = "grouped"

# Ações possíveis na trilha de auditoria do curador
ACTION_APPROVE = "APPROVE"
ACTION_REJECT = "REJECT"
ACTION_GROUP = "GROUP"
ACTION_AUTO_THUMBS_DOWN = "AUTO_REJECT_THUMBS_DOWN"
ACTION_PRO_OVERRIDE = "PRO_OVERRIDE"

# Origens da decisão
SOURCE_FLASH = "flash"
SOURCE_PRO = "pro"
SOURCE_AUTO = "auto"

LESSON_FLASH_APROVOU_PRO_REJEITOU = "flash_approved_pro_rejected"
LESSON_FLASH_REJEITOU_PRO_APROVOU = "flash_rejected_pro_approved"

# DDL — statements individuais (para futura migração ao Postgres)
_DDL_STATEMENTS = [
    # ── Staging de turnos (a principal novidade da Fase 2) ──────────────
    """
    CREATE TABLE IF NOT EXISTS memory_staging (
        id              TEXT PRIMARY KEY,
        cpf             TEXT NOT NULL,
        session_id      TEXT NOT NULL,
        agent_name      TEXT,
        intent          TEXT,
        tools_called    TEXT,
        valor_solicitado REAL,
        decisao         TEXT,
        user_message    TEXT NOT NULL,
        agent_response  TEXT NOT NULL,
        user_feedback   INTEGER,
        status          TEXT NOT NULL DEFAULT 'pending',
        created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        processed_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_staging_status ON memory_staging(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_staging_cpf ON memory_staging(cpf, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_staging_session ON memory_staging(session_id)",

    # ── Camada 1 — Lições de auditoria ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS curator_lessons (
        id           TEXT PRIMARY KEY,
        direction    TEXT NOT NULL,
        example_text TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_curator_lessons_dir ON curator_lessons(direction, created_at DESC)",

    # ── Camada 2 — Padrões dinâmicos ────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS curator_dynamic_patterns (
        id         TEXT PRIMARY KEY,
        pattern    TEXT NOT NULL UNIQUE,
        source     TEXT NOT NULL DEFAULT 'audit',
        hit_count  INTEGER NOT NULL DEFAULT 1,
        last_seen  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ── Camada 3 — Estatísticas de batch ────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS curator_batch_stats (
        id            TEXT PRIMARY KEY,
        batch_number  INTEGER NOT NULL,
        total         INTEGER NOT NULL,
        approved      INTEGER NOT NULL,
        rejected      INTEGER NOT NULL,
        grouped       INTEGER NOT NULL,
        approval_rate REAL NOT NULL,
        created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_curator_batch_stats_created ON curator_batch_stats(created_at DESC)",

    # ── Trilha de auditoria do curador (1 registro por decisão) ───────
    """
    CREATE TABLE IF NOT EXISTS curator_decisions (
        id             TEXT PRIMARY KEY,
        turno_id       TEXT NOT NULL,
        batch_number   INTEGER,
        action         TEXT NOT NULL,        -- APPROVE | REJECT | GROUP | AUTO_REJECT_THUMBS_DOWN
        source         TEXT NOT NULL,        -- flash | pro | auto | pro_override
        reason         TEXT,
        intent         TEXT,
        cpf            TEXT,
        vector_collection TEXT,              -- interacoes_curadas | feedbacks_negativos | NULL
        decided_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_curator_decisions_turno ON curator_decisions(turno_id)",
    "CREATE INDEX IF NOT EXISTS idx_curator_decisions_time ON curator_decisions(decided_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_curator_decisions_batch ON curator_decisions(batch_number)",

    # ── LLM-as-judge — avaliações nightly (ADR-022) ────────────────────
    """
    CREATE TABLE IF NOT EXISTS judge_scores (
        id              TEXT PRIMARY KEY,
        turno_id        TEXT NOT NULL,
        precisao        INTEGER,
        tom             INTEGER,
        completude      INTEGER,
        score_total     REAL,
        comentario      TEXT,
        judged_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_judge_scores_turno ON judge_scores(turno_id)",
    "CREATE INDEX IF NOT EXISTS idx_judge_scores_time ON judge_scores(judged_at DESC)",
]

# Migrações idempotentes — executadas após os CREATE TABLE. Cada ALTER TABLE
# pode falhar com "duplicate column"; o erro é capturado silenciosamente.
# Mantenha commands aqui (nunca remova) mesmo depois de aplicadas — são histórico.
_MIGRATIONS: list[str] = [
    # ADR-023 — Golden set + worker com source tag
    "ALTER TABLE curator_lessons ADD COLUMN source TEXT NOT NULL DEFAULT 'worker'",
    "ALTER TABLE curator_lessons ADD COLUMN aplicavel_a TEXT",   # JSON array de agentes
    "ALTER TABLE curator_lessons ADD COLUMN motivo TEXT",
    "ALTER TABLE curator_lessons ADD COLUMN ativa INTEGER NOT NULL DEFAULT 1",
]

# Valores de `source` em curator_lessons e nas collections learned_*
LESSON_SOURCE_GOLDEN = "golden"
LESSON_SOURCE_WORKER = "worker"


class StagingStore:
    """Facade sobre o SQLite. Toda a infra de curadoria passa por aqui.

    Usa conexões por operação — SQLite é leve e não justifica pool próprio.
    Operações são assíncronas via aiosqlite (evita bloquear o event loop).
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._initialized = False
        self._sync_lock = threading.Lock()
        self._sync_initialized = False

    async def init(self) -> None:
        """Cria o DB (se não existir) e aplica o schema. Idempotente."""
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as conn:
            for stmt in _DDL_STATEMENTS:
                await conn.execute(stmt)
            for stmt in _MIGRATIONS:
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    # ALTER TABLE ADD COLUMN já aplicada é o caso esperado.
                    logger.debug("Migração ignorada (%s): %s", stmt[:60], exc)
            await conn.commit()
        self._initialized = True
        logger.info("StagingStore inicializado em %s", self._db_path)

    async def _ensure_init(self) -> None:
        if not self._initialized:
            await self.init()

    def _ensure_init_sync(self) -> None:
        """Inicializa via API síncrona — usado pelos nós do grafo."""
        if self._sync_initialized:
            return
        with self._sync_lock:
            if self._sync_initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                for stmt in _DDL_STATEMENTS:
                    conn.execute(stmt)
                for stmt in _MIGRATIONS:
                    try:
                        conn.execute(stmt)
                    except Exception as exc:
                        logger.debug("Migração ignorada (%s): %s", stmt[:60], exc)
                conn.commit()
            self._sync_initialized = True
            logger.info("StagingStore (sync) inicializado em %s", self._db_path)

    # ── API SÍNCRONA (hot path do grafo LangGraph) ─────────────────────
    # O grafo roda síncrono por padrão. Gravar em SQLite local leva <5ms
    # — aceitável como custo do hot path em troca da simplicidade.

    def registrar_turno_sync(
        self,
        *,
        cpf: str,
        session_id: str,
        user_message: str,
        agent_response: str,
        agent_name: str | None = None,
        intent: str | None = None,
        tools_called: list | None = None,
        valor_solicitado: float | None = None,
        decisao: str | None = None,
    ) -> str:
        """Versão síncrona de registrar_turno. Retorna o id gerado.

        Não levanta — loga e retorna string vazia em caso de falha,
        porque não queremos que a curadoria quebre o chat.
        """
        try:
            self._ensure_init_sync()
            turno_id = str(uuid.uuid4())
            tools_json = (
                json.dumps(tools_called, ensure_ascii=False) if tools_called else None
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO memory_staging
                      (id, cpf, session_id, agent_name, intent, tools_called,
                       valor_solicitado, decisao, user_message, agent_response, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turno_id, cpf, session_id, agent_name, intent, tools_json,
                        valor_solicitado, decisao, user_message, agent_response,
                        STATUS_PENDING,
                    ),
                )
                conn.commit()
            return turno_id
        except Exception:
            logger.exception("Falha ao registrar turno no staging (ignorando)")
            return ""

    # ── Staging: gravação por turno (hot path) ─────────────────────────

    async def registrar_turno(
        self,
        *,
        cpf: str,
        session_id: str,
        user_message: str,
        agent_response: str,
        agent_name: str | None = None,
        intent: str | None = None,
        tools_called: list | None = None,
        valor_solicitado: float | None = None,
        decisao: str | None = None,
    ) -> str:
        """Insere um turno no staging. Retorna o id gerado.

        Chamada pelo grafo após cada resposta importante. DEVE ser rápida:
        insert simples + commit, sem embeddings nem chamadas externas.
        """
        await self._ensure_init()
        turno_id = str(uuid.uuid4())
        tools_json = json.dumps(tools_called, ensure_ascii=False) if tools_called else None

        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO memory_staging
                  (id, cpf, session_id, agent_name, intent, tools_called,
                   valor_solicitado, decisao, user_message, agent_response, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turno_id, cpf, session_id, agent_name, intent, tools_json,
                    valor_solicitado, decisao, user_message, agent_response,
                    STATUS_PENDING,
                ),
            )
            await conn.commit()
        return turno_id

    async def registrar_feedback(self, turno_id: str, feedback: int) -> bool:
        """Grava thumbs up/down (-1 ou +1) para um turno. Retorna True se atualizou."""
        if feedback not in (-1, 1):
            raise ValueError("feedback deve ser -1 (down) ou +1 (up)")
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            cursor = await conn.execute(
                "UPDATE memory_staging SET user_feedback = ? WHERE id = ?",
                (feedback, turno_id),
            )
            await conn.commit()
            return (cursor.rowcount or 0) > 0

    # ── Staging: leitura para curadoria ─────────────────────────────────

    async def contar_pendentes(self) -> int:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM memory_staging WHERE status = ?",
                (STATUS_PENDING,),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def listar_pendentes(self, limit: int = 20) -> list[dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """
                SELECT id, cpf, session_id, agent_name, intent, tools_called,
                       valor_solicitado, decisao, user_message, agent_response,
                       user_feedback, status, created_at
                FROM memory_staging
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (STATUS_PENDING, limit),
            ) as cur:
                rows = await cur.fetchall()

        out = []
        for r in rows:
            item = dict(r)
            if item.get("tools_called"):
                try:
                    item["tools_called"] = json.loads(item["tools_called"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(item)
        return out

    async def marcar_status(self, ids: list[str], status: str) -> int:
        """Marca um conjunto de turnos com o status dado. Retorna quantos mudaram."""
        if not ids:
            return 0
        if status not in (STATUS_APPROVED, STATUS_REJECTED, STATUS_GROUPED, STATUS_PENDING):
            raise ValueError(f"status inválido: {status}")
        await self._ensure_init()
        placeholders = ",".join("?" for _ in ids)
        async with aiosqlite.connect(self._db_path) as conn:
            cursor = await conn.execute(
                f"""
                UPDATE memory_staging
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (status, *ids),
            )
            await conn.commit()
            return cursor.rowcount or 0

    async def listar_recentes(
        self,
        limit: int = 50,
        intent: str | None = None,
        feedback: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Lista turnos para o dashboard de curadoria (filtros opcionais)."""
        await self._ensure_init()
        clauses = []
        params: list = []
        if intent:
            clauses.append("intent = ?")
            params.append(intent)
        if feedback is not None:
            clauses.append("user_feedback = ?")
            params.append(feedback)
        if status:
            clauses.append("status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                f"""
                SELECT id, cpf, session_id, agent_name, intent,
                       valor_solicitado, decisao, user_message, agent_response,
                       user_feedback, status, created_at
                FROM memory_staging
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(params),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── Camada 1 — Lições ──────────────────────────────────────────────

    async def salvar_licao(self, direction: str, example_text: str) -> str:
        await self._ensure_init()
        licao_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "INSERT INTO curator_lessons (id, direction, example_text) VALUES (?, ?, ?)",
                (licao_id, direction, example_text),
            )
            await conn.commit()
        return licao_id

    async def salvar_licao_golden(
        self,
        *,
        licao_id: str,
        regra: str,
        motivo: str | None,
        aplicavel_a: list[str],
        source: str = LESSON_SOURCE_GOLDEN,
        ativa: bool = True,
    ) -> None:
        """Upsert de lição (golden ou worker) com tags de aplicabilidade.

        `aplicavel_a` é uma lista de agentes ('cambio', 'credito', ...); serializada
        em JSON no campo para flexibilidade. O filtro de runtime usa LIKE no JSON.
        """
        await self._ensure_init()
        aplicavel_json = json.dumps(aplicavel_a, ensure_ascii=False)
        async with aiosqlite.connect(self._db_path) as conn:
            # UPSERT by id (permite re-seed sem duplicar)
            await conn.execute(
                """
                INSERT INTO curator_lessons
                    (id, direction, example_text, source, aplicavel_a, motivo, ativa)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    example_text = excluded.example_text,
                    source       = excluded.source,
                    aplicavel_a  = excluded.aplicavel_a,
                    motivo       = excluded.motivo,
                    ativa        = excluded.ativa
                """,
                (
                    licao_id,
                    "golden" if source == LESSON_SOURCE_GOLDEN else "worker",
                    regra,
                    source,
                    aplicavel_json,
                    motivo or "",
                    1 if ativa else 0,
                ),
            )
            await conn.commit()

    async def listar_licoes_ativas(self, agente: str | None = None) -> list[dict]:
        """Retorna lições ativas, filtrando por agente aplicável.

        Se `agente` for None, retorna todas as ativas. Caso contrário, só as que
        contêm o agente na lista `aplicavel_a` (match por LIKE no JSON).
        Ordenação: golden primeiro, depois mais recentes.
        """
        await self._ensure_init()
        sql = """
            SELECT id, example_text, source, aplicavel_a, motivo, ativa, created_at
            FROM curator_lessons
            WHERE ativa = 1
        """
        params: list = []
        if agente:
            sql += " AND (aplicavel_a LIKE ? OR aplicavel_a IS NULL)"
            params.append(f'%"{agente}"%')
        sql += " ORDER BY CASE source WHEN 'golden' THEN 0 ELSE 1 END, created_at DESC"
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(sql, tuple(params)) as cur:
                rows = await cur.fetchall()
        resultado: list[dict] = []
        for r in rows:
            d = dict(r)
            try:
                d["aplicavel_a"] = json.loads(d.get("aplicavel_a") or "[]")
            except (TypeError, ValueError):
                d["aplicavel_a"] = []
            d["ativa"] = bool(d.get("ativa"))
            resultado.append(d)
        return resultado

    async def obter_licoes(self, per_direction: int = 5) -> dict:
        """Retorna até N lições mais recentes de cada direção."""
        await self._ensure_init()
        out = {
            LESSON_FLASH_APROVOU_PRO_REJEITOU: [],
            LESSON_FLASH_REJEITOU_PRO_APROVOU: [],
        }
        async with aiosqlite.connect(self._db_path) as conn:
            for direction in list(out.keys()):
                async with conn.execute(
                    """
                    SELECT example_text FROM curator_lessons
                    WHERE direction = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (direction, per_direction),
                ) as cur:
                    rows = await cur.fetchall()
                out[direction] = [r[0] for r in rows]
        return out

    # ── Camada 2 — Padrões dinâmicos ────────────────────────────────────

    async def salvar_padrao(self, pattern: str, source: str = "audit") -> None:
        """Upsert de padrão: incrementa hit_count se já existir."""
        await self._ensure_init()
        pat = pattern[:500]  # limita para indexação
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO curator_dynamic_patterns (id, pattern, source, hit_count, last_seen)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(pattern) DO UPDATE SET
                  hit_count = hit_count + 1,
                  last_seen = CURRENT_TIMESTAMP
                """,
                (str(uuid.uuid4()), pat, source),
            )
            await conn.commit()

    async def obter_padroes(self, limit: int = 10) -> list[str]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            async with conn.execute(
                """
                SELECT pattern FROM curator_dynamic_patterns
                ORDER BY hit_count DESC, last_seen DESC
                LIMIT ?
                """,
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [r[0] for r in rows]

    # ── Camada 3 — Estatísticas de batch ────────────────────────────────

    async def salvar_stats_batch(
        self,
        *,
        batch_number: int,
        total: int,
        approved: int,
        rejected: int,
        grouped: int,
    ) -> None:
        await self._ensure_init()
        rate = approved / total if total > 0 else 0.0
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO curator_batch_stats
                  (id, batch_number, total, approved, rejected, grouped, approval_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), batch_number, total, approved, rejected, grouped, rate),
            )
            await conn.commit()

    # ── Trilha de auditoria — decisões do curador ─────────────────────

    async def salvar_decisao(
        self,
        *,
        turno_id: str,
        action: str,
        source: str,
        batch_number: int | None = None,
        reason: str | None = None,
        intent: str | None = None,
        cpf: str | None = None,
        vector_collection: str | None = None,
    ) -> str:
        """Persiste uma decisão do curador (auditoria).

        `action`: APPROVE / REJECT / GROUP / AUTO_REJECT_THUMBS_DOWN / PRO_OVERRIDE
        `source`: flash / pro / auto / pro_override
        Falha silenciosa: auditoria nunca pode quebrar o worker.
        """
        await self._ensure_init()
        dec_id = str(uuid.uuid4())
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute(
                    """
                    INSERT INTO curator_decisions
                      (id, turno_id, batch_number, action, source, reason,
                       intent, cpf, vector_collection)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dec_id, turno_id, batch_number, action, source, reason,
                        intent, cpf, vector_collection,
                    ),
                )
                await conn.commit()
        except Exception:
            logger.exception("Falha ao gravar decisão de auditoria (ignorando)")
            return ""
        return dec_id

    async def listar_decisoes(
        self,
        limit: int = 100,
        action: str | None = None,
        source: str | None = None,
        batch_number: int | None = None,
    ) -> list[dict]:
        """Lista decisões recentes (com JOIN leve para trazer user/agent do turno)."""
        await self._ensure_init()
        clauses = []
        params: list = []
        if action:
            clauses.append("d.action = ?")
            params.append(action)
        if source:
            clauses.append("d.source = ?")
            params.append(source)
        if batch_number is not None:
            clauses.append("d.batch_number = ?")
            params.append(batch_number)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                f"""
                SELECT d.id, d.turno_id, d.batch_number, d.action, d.source,
                       d.reason, d.intent, d.cpf, d.vector_collection, d.decided_at,
                       s.user_message, s.agent_response, s.agent_name, s.user_feedback
                FROM curator_decisions d
                LEFT JOIN memory_staging s ON s.id = d.turno_id
                {where}
                ORDER BY d.decided_at DESC
                LIMIT ?
                """,
                tuple(params),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def contar_decisoes_por_action(self) -> dict[str, int]:
        """Contadores agregados das decisões (para o topo do dashboard)."""
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            async with conn.execute(
                "SELECT action, COUNT(*) FROM curator_decisions GROUP BY action",
            ) as cur:
                rows = await cur.fetchall()
        return {r[0]: int(r[1]) for r in rows}

    # ── LLM-as-judge (ADR-022) ─────────────────────────────────────────

    async def amostrar_turnos_para_julgamento(self, limit: int = 20) -> list[dict]:
        """Amostra aleatória de turnos aprovados ainda não julgados."""
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """
                SELECT s.id, s.cpf, s.agent_name, s.intent, s.user_message,
                       s.agent_response, s.decisao, s.user_feedback
                FROM memory_staging s
                LEFT JOIN judge_scores j ON j.turno_id = s.id
                WHERE s.status = ? AND j.id IS NULL
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (STATUS_APPROVED, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def salvar_judge_score(
        self,
        *,
        turno_id: str,
        precisao: int,
        tom: int,
        completude: int,
        comentario: str = "",
    ) -> str:
        """Persiste um score do juiz (cada critério de 1 a 5)."""
        await self._ensure_init()
        score_id = str(uuid.uuid4())
        total = (precisao + tom + completude) / 3.0
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO judge_scores
                  (id, turno_id, precisao, tom, completude, score_total, comentario)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (score_id, turno_id, precisao, tom, completude, total, comentario),
            )
            await conn.commit()
        return score_id

    async def estatisticas_judge(self, days: int = 30) -> dict:
        """Retorna média e contagem dos scores dos últimos N dias."""
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                f"""
                SELECT COUNT(*)    AS n,
                       AVG(precisao)   AS avg_precisao,
                       AVG(tom)        AS avg_tom,
                       AVG(completude) AS avg_completude,
                       AVG(score_total) AS avg_total,
                       MIN(score_total) AS min_total
                FROM judge_scores
                WHERE judged_at >= datetime('now', '-{int(days)} days')
                """
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else {}

    async def obter_taxa_aprovacao(self, last_n: int = 10) -> float | None:
        """Taxa média dos últimos N batches. None se não houver dados."""
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as conn:
            async with conn.execute(
                """
                SELECT AVG(approval_rate) FROM (
                  SELECT approval_rate FROM curator_batch_stats
                  ORDER BY created_at DESC LIMIT ?
                )
                """,
                (last_n,),
            ) as cur:
                row = await cur.fetchone()
        if not row or row[0] is None:
            return None
        return float(row[0])


# Instância compartilhada — inicialização lazy no primeiro `await`
staging_store = StagingStore()
