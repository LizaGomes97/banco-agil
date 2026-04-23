"""
Orquestrador do simulador de clientes — Banco Ágil.

Modos de execução:
    python -m simulador.main                   → roda todos os cenários sequencialmente
    python -m simulador.main --modo carga      → N clientes em paralelo
    python -m simulador.main --modo auth       → apenas fluxos de autenticação
    python -m simulador.main --modo guardrail  → apenas testes de guardrails
    python -m simulador.main --modo rapido     → 1 cliente, todas as categorias

Flags:
    --clientes N        número de clientes paralelos (padrão: 3, máximo: 5)
    --sem-relatorio     não salva arquivos em simulador/reports/
    --verbose           mostra resposta completa do agente
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime
from typing import List

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .chat_client import BancoAgilClient
from .config import BACKEND_URL, CLIENTES, DELAY_ENTRE_PERGUNTAS_S, ClienteSimulado
from .evaluator import EvaluationResult, avaliar, avaliar_auth
from .logging_setup import get_logger, setup_logging
from .question_bank import (
    QuestionItem,
    get_perguntas_guardrail,
    get_perguntas_pos_auth,
    PERGUNTAS_SAUDACAO,
)
from .reporter import save_json, save_markdown

console = Console() if HAS_RICH else None
logger = get_logger("main")


def _log(msg: str, estilo: str = "") -> None:
    if HAS_RICH and console:
        console.print(msg, style=estilo)
    else:
        print(msg)


# ── Cenários ──────────────────────────────────────────────────────────────────

async def cenario_auth_valida(cliente: ClienteSimulado, verbose: bool) -> List[EvaluationResult]:
    """Autentica com credenciais corretas e faz perguntas bancárias."""
    resultados: List[EvaluationResult] = []

    logger.info("=== CENÁRIO: auth_valida | cliente=%s ===", cliente.nome)
    async with BancoAgilClient() as api:
        _log(f"\n[bold cyan]▶ Auth válida:[/bold cyan] {cliente.nome}" if HAS_RICH else
             f"\n>> Auth válida: {cliente.nome}")

        r = await api.autenticar(cliente)
        ev = avaliar_auth(r, cliente.nome, esperava_sucesso=True)
        resultados.append(ev)
        _exibir_resultado(ev, r.reply if verbose else None)
        logger.info(
            "AUTH resultado: score=%.1f passou=%s authenticated=%s encerrado=%s problemas=%s",
            ev.score, ev.passou(), r.authenticated, r.encerrado, ev.problemas,
        )

        if not r.authenticated:
            _log("  [red]Auth falhou — pulando perguntas pós-auth[/red]" if HAS_RICH
                 else "  ERRO: Auth falhou — pulando perguntas pós-auth")
            logger.warning("Auth falhou para %s — pulando perguntas", cliente.nome)
            return resultados

        for item in get_perguntas_pos_auth():
            logger.debug("Pergunta [%s]: '%s'", item.categoria, item.pergunta[:80])
            logger.debug("Aguardando %.1fs (rate limit Gemini)...", DELAY_ENTRE_PERGUNTAS_S)
            await asyncio.sleep(DELAY_ENTRE_PERGUNTAS_S)
            resp = await api.chat(item.pergunta)
            ev = avaliar(resp, item, cliente.nome)
            resultados.append(ev)
            _exibir_resultado(ev, resp.reply if verbose else None)
            if ev.problemas:
                logger.warning(
                    "[%s] score=%.1f problemas=%s | reply='%s'",
                    item.categoria, ev.score, ev.problemas, resp.reply[:150],
                )
            else:
                logger.info("[%s] score=%.1f OK", item.categoria, ev.score)

    logger.info("=== FIM auth_valida | cliente=%s | interações=%d ===", cliente.nome, len(resultados))
    return resultados


async def cenario_auth_invalida_recuperacao(cliente: ClienteSimulado, verbose: bool) -> List[EvaluationResult]:
    """1 tentativa errada, depois autentica corretamente."""
    resultados: List[EvaluationResult] = []

    logger.info("=== CENÁRIO: auth_invalida_recuperacao | cliente=%s ===", cliente.nome)
    async with BancoAgilClient() as api:
        _log(f"\n[bold yellow]▶ Auth inválida→recuperação:[/bold yellow] {cliente.nome}" if HAS_RICH
             else f"\n>> Auth inválida→recuperação: {cliente.nome}")

        r = await api.autenticar(cliente, usar_data_invalida=True)
        ev = avaliar_auth(r, cliente.nome, esperava_sucesso=False, tentativa=1)
        resultados.append(ev)
        _exibir_resultado(ev, r.reply if verbose else None)
        logger.info("Tentativa 1 (inválida): score=%.1f authenticated=%s reply='%s'",
                    ev.score, r.authenticated, r.reply[:100])

        await asyncio.sleep(DELAY_ENTRE_PERGUNTAS_S)
        r2 = await api.autenticar(cliente)
        ev2 = avaliar_auth(r2, cliente.nome, esperava_sucesso=True, tentativa=2)
        resultados.append(ev2)
        _exibir_resultado(ev2, r2.reply if verbose else None)
        logger.info("Tentativa 2 (válida): score=%.1f authenticated=%s reply='%s'",
                    ev2.score, r2.authenticated, r2.reply[:100])

    logger.info("=== FIM auth_invalida_recuperacao | cliente=%s ===", cliente.nome)
    return resultados


async def cenario_bloqueio_3_tentativas(cliente: ClienteSimulado, verbose: bool) -> List[EvaluationResult]:
    """3 tentativas com data inválida → deve encerrar a sessão."""
    resultados: List[EvaluationResult] = []

    logger.info("=== CENÁRIO: bloqueio_3_tentativas | cliente=%s ===", cliente.nome)
    async with BancoAgilClient() as api:
        _log(f"\n[bold red]▶ Bloqueio 3 tentativas:[/bold red] {cliente.nome}" if HAS_RICH
             else f"\n>> Bloqueio 3 tentativas: {cliente.nome}")

        for tentativa in range(1, 4):
            if tentativa > 1:
                await asyncio.sleep(DELAY_ENTRE_PERGUNTAS_S)
            r = await api.autenticar(cliente, usar_data_invalida=True)
            ev = avaliar_auth(r, cliente.nome, esperava_sucesso=False, tentativa=tentativa)
            resultados.append(ev)
            _exibir_resultado(ev, r.reply if verbose else None)
            logger.info(
                "Tentativa %d/3: authenticated=%s encerrado=%s reply='%s'",
                tentativa, r.authenticated, r.encerrado, r.reply[:120],
            )

            if r.encerrado:
                _log(f"  [green]✓ Sessão encerrada na tentativa {tentativa} (correto)[/green]"
                     if HAS_RICH else f"  OK: Sessão encerrada na tentativa {tentativa}")
                logger.info("Bloqueio ativado na tentativa %d (comportamento correto)", tentativa)
                break
        else:
            logger.error(
                "BUG DE SEGURANÇA: sessão de %s NÃO foi encerrada após 3 tentativas inválidas!",
                cliente.nome,
            )
            ev_bug = EvaluationResult(
                pergunta="[VERIFICAÇÃO] Sessão deve estar encerrada após 3 falhas",
                categoria="autenticacao_bloqueio",
                cliente_nome=cliente.nome,
                score=0.0,
                problemas=["Sessão não foi encerrada após 3 tentativas inválidas — bug de segurança!"],
            )
            resultados.append(ev_bug)
            _log("  [bold red]BUG: Sessão não encerrada após 3 falhas![/bold red]" if HAS_RICH
                 else "  BUG: Sessão não encerrada após 3 falhas!")

    logger.info("=== FIM bloqueio_3_tentativas ===")
    return resultados


async def cenario_guardrail(verbose: bool) -> List[EvaluationResult]:
    """Testa guardrails sem autenticação."""
    resultados: List[EvaluationResult] = []

    logger.info("=== CENÁRIO: guardrails ===")
    async with BancoAgilClient() as api:
        _log(f"\n[bold magenta]▶ Guardrails[/bold magenta]" if HAS_RICH
             else f"\n>> Guardrails")

        for item in get_perguntas_guardrail():
            logger.debug("Guardrail [%s]: '%s'", item.categoria, item.pergunta[:80])
            await asyncio.sleep(DELAY_ENTRE_PERGUNTAS_S)
            resp = await api.chat(item.pergunta)
            ev = avaliar(resp, item, "Anônimo")
            resultados.append(ev)
            _exibir_resultado(ev, resp.reply if verbose else None)
            if ev.problemas:
                logger.warning(
                    "GUARDRAIL [%s] score=%.1f problemas=%s | reply='%s'",
                    item.categoria, ev.score, ev.problemas, resp.reply[:150],
                )
            else:
                logger.info("GUARDRAIL [%s] score=%.1f OK", item.categoria, ev.score)

    logger.info("=== FIM guardrails ===")
    return resultados


# ── Helpers de exibição ───────────────────────────────────────────────────────

def _exibir_resultado(ev: EvaluationResult, reply: str | None = None) -> None:
    passou = ev.passou()
    if HAS_RICH and console:
        cor = "green" if passou else ("yellow" if ev.score >= 5 else "red")
        icone = "✅" if passou else ("⚠️" if ev.score >= 5 else "❌")
        console.print(
            f"  {icone} [{cor}]{ev.categoria}[/{cor}] "
            f"score=[bold]{ev.score}/10[/bold] "
            f"lat={ev.latencia_s:.1f}s"
        )
        for p in ev.problemas:
            console.print(f"    [red]↳ {p}[/red]")
    else:
        status = "OK" if passou else "FALHA"
        print(f"  [{status}] {ev.categoria} score={ev.score}/10 lat={ev.latencia_s:.1f}s")
        for p in ev.problemas:
            print(f"    >> {p}")

    if reply:
        _log(f"  [dim]Resposta: {reply[:300]}[/dim]" if HAS_RICH else f"  Resposta: {reply[:300]}")


def _exibir_resumo(resultados: List[EvaluationResult]) -> None:
    total = len(resultados)
    passaram = sum(1 for r in resultados if r.passou())
    score_medio = sum(r.score for r in resultados) / total if total else 0

    _log("\n" + "─" * 60)
    if HAS_RICH and console:
        cor = "green" if passaram == total else ("yellow" if passaram / total >= 0.7 else "red")
        console.print(
            f"\n[bold]Resultado Final:[/bold] "
            f"[{cor}]{passaram}/{total} passaram[/{cor}] | "
            f"score médio: [bold]{score_medio:.1f}/10[/bold]"
        )
    else:
        print(f"\nResultado: {passaram}/{total} passaram | score médio: {score_medio:.1f}/10")

    # Falhas críticas
    criticas = [r for r in resultados if any("segurança" in p.lower() or "crítico" in p.lower()
                                              or "INVÁLIDAS" in p for p in r.problemas)]
    if criticas:
        _log("\n[bold red]⛔ FALHAS CRÍTICAS DE SEGURANÇA:[/bold red]" if HAS_RICH
             else "\n!! FALHAS CRÍTICAS DE SEGURANÇA:")
        for r in criticas:
            for p in r.problemas:
                _log(f"  • [{r.categoria}] {r.cliente_nome}: {p}", "red")


# ── Orquestração paralela ─────────────────────────────────────────────────────

async def executar_cliente(cliente: ClienteSimulado, verbose: bool) -> List[EvaluationResult]:
    """Executa todos os cenários para um cliente."""
    resultados = []
    resultados += await cenario_auth_valida(cliente, verbose)
    resultados += await cenario_auth_invalida_recuperacao(cliente, verbose)
    return resultados


async def run_modo_completo(clientes: List[ClienteSimulado], verbose: bool) -> List[EvaluationResult]:
    """Roda todos os cenários sequencialmente para evitar rate limit do Gemini."""
    resultados: List[EvaluationResult] = []

    for cliente in clientes:
        resultados += await executar_cliente(cliente, verbose)

    # Bloqueio 3 tentativas (1 cliente basta)
    resultados += await cenario_bloqueio_3_tentativas(clientes[0], verbose)

    # Guardrails (1 sessão anônima)
    resultados += await cenario_guardrail(verbose)

    return resultados


async def run_modo_auth(clientes: List[ClienteSimulado], verbose: bool) -> List[EvaluationResult]:
    resultados = []
    for c in clientes:
        resultados += await cenario_auth_valida(c, verbose)
        resultados += await cenario_auth_invalida_recuperacao(c, verbose)
    resultados += await cenario_bloqueio_3_tentativas(clientes[0], verbose)
    return resultados


async def run_modo_guardrail(verbose: bool) -> List[EvaluationResult]:
    return await cenario_guardrail(verbose)


async def run_modo_rapido(clientes: List[ClienteSimulado], verbose: bool) -> List[EvaluationResult]:
    """1 cliente, cenário completo mais rápido possível."""
    cliente = random.choice(clientes)
    resultados = await cenario_auth_valida(cliente, verbose)
    resultados += await cenario_guardrail(verbose)
    return resultados


# ── Health check ──────────────────────────────────────────────────────────────

async def _verificar_api() -> bool:
    async with BancoAgilClient() as api:
        ok = await api.health()
    return ok


# ── Entrypoint ────────────────────────────────────────────────────────────────

async def main_async(args: argparse.Namespace) -> int:
    setup_logging(verbose_console=args.verbose)
    session_id = str(uuid.uuid4())[:8]

    logger.info("╔══ SIMULADOR BANCO ÁGIL | sessão=%s modo=%s clientes=%d ══╗",
                session_id, args.modo, args.clientes)

    _log(f"\n{'='*60}")
    _log(f"[bold]Simulador Banco Ágil[/bold] | sessão {session_id}" if HAS_RICH
         else f"Simulador Banco Ágil | sessão {session_id}")
    _log(f"Modo: [cyan]{args.modo}[/cyan] | Clientes: {args.clientes}" if HAS_RICH
         else f"Modo: {args.modo} | Clientes: {args.clientes}")
    _log(f"{'='*60}\n")

    # Verificar API
    _log("Verificando API...", "dim")
    if not await _verificar_api():
        logger.error("API offline em %s — abortar simulação", BACKEND_URL)
        _log("[bold red]ERRO: API não está respondendo. Inicie o servidor antes de rodar o simulador.[/bold red]"
             if HAS_RICH else "ERRO: API offline. Rode: uvicorn api.main:app --reload")
        return 1
    logger.info("API online: %s", BACKEND_URL)
    _log("[green]✓ API online[/green]" if HAS_RICH else "OK: API online")

    clientes = CLIENTES[: args.clientes]

    # Executar modo escolhido
    if args.modo == "carga" or args.modo == "completo":
        resultados = await run_modo_completo(clientes, args.verbose)
    elif args.modo == "auth":
        resultados = await run_modo_auth(clientes, args.verbose)
    elif args.modo == "guardrail":
        resultados = await run_modo_guardrail(args.verbose)
    elif args.modo == "rapido":
        resultados = await run_modo_rapido(clientes, args.verbose)
    else:
        resultados = await run_modo_completo(clientes, args.verbose)

    _exibir_resumo(resultados)

    # Log do resumo final no arquivo
    total = len(resultados)
    passaram = sum(1 for r in resultados if r.passou())
    score_medio = sum(r.score for r in resultados) / total if total else 0
    falhas = [r for r in resultados if not r.passou()]
    logger.info(
        "╚══ RESULTADO FINAL | sessão=%s | %d/%d passaram | score_medio=%.1f ══╝",
        session_id, passaram, total, score_medio,
    )
    for r in falhas:
        logger.warning(
            "FALHA [%s] cliente='%s' score=%.1f lat=%.1fs | %s",
            r.categoria, r.cliente_nome, r.score, r.latencia_s,
            " | ".join(r.problemas),
        )

    # Salvar relatórios
    if not args.sem_relatorio and resultados:
        json_path = save_json(resultados, session_id)
        md_path = save_markdown(resultados, session_id)
        _log(f"\n[dim]Relatórios salvos:[/dim]" if HAS_RICH else "\nRelatórios salvos:")
        _log(f"  [dim]{json_path}[/dim]" if HAS_RICH else f"  {json_path}")
        _log(f"  [dim]{md_path}[/dim]" if HAS_RICH else f"  {md_path}")

    # Retorna código de saída 1 se algum teste falhou (útil para CI)
    houve_falha = any(not r.passou() for r in resultados)
    return 1 if houve_falha else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador de clientes do Banco Ágil")
    parser.add_argument(
        "--modo",
        choices=["completo", "carga", "auth", "guardrail", "rapido"],
        default="completo",
        help="Modo de execução (padrão: completo)",
    )
    parser.add_argument(
        "--clientes",
        type=int,
        default=3,
        choices=range(1, 6),
        metavar="N",
        help="Número de clientes a simular (1–5, padrão: 3)",
    )
    parser.add_argument(
        "--sem-relatorio",
        action="store_true",
        help="Não salva arquivos de relatório",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Exibe a resposta completa do agente",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
