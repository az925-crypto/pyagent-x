import os
import time
import json
import asyncio
from datetime import datetime
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


DEPTH_CONFIG = {
    1: {"maxTurns": 10, "label": "Quick"},
    2: {"maxTurns": 30, "label": "Normal"},
    3: {"maxTurns": 50, "label": "Deep"},
}


class InvestigationUI:
    def __init__(self, agent, console: Console):
        self.agent = agent
        self.console = console
        self.investigation_active = False
        self._inv_triggered = False
        self._running = False
        self.depth = 2

    def _on_tool_call(self, name: str, args: dict):
        arg_str = " ".join(f"{k}={str(v)[:40]}" for k, v in args.items())

        if name == "init_investigation":
            self.investigation_active = True
            self._inv_triggered = True
            target = str(args.get("target", "TARGET"))
            self.console.print()
            self.console.print(Panel(f"[bold cyan]INVESTIGATION: {target}[/bold cyan]", border_style="cyan"))
            self.console.print()
        elif name == "add_finding":
            self.console.print(f"  [yellow]\U0001f50d {args.get('detail', '')[:120]}[/yellow]")
        else:
            self.console.print(f"  [cyan]> {name}[/cyan] [dim]{arg_str}[/dim]")

    def _on_tool_result(self, name: str, result: dict, duration_ms: int):
        has_error = isinstance(result, dict) and "error" in result
        if has_error:
            self.console.print(f"  [red]\u2717 {name}: {str(result.get('error', ''))[:80]} ({_fmt(duration_ms)})[/red]")
        else:
            self.console.print(f"  [green]\u2713 {name} ({_fmt(duration_ms)})[/green]")

    async def run(self):
        self._running = True
        agent = self.agent
        self.investigation_active = False

        agent.callbacks["onToolCall"] = self._on_tool_call
        agent.callbacks["onToolResult"] = self._on_tool_result

        self.console.print()
        self.console.print("[yellow]Chat mode — type a target to investigate or just chat![/yellow]")
        cfg = DEPTH_CONFIG[self.depth]
        self.console.print(f"[dim]Commands: 'exit' to quit, 'clear' to clear, 'review' for findings, 'depth 1/2/3', '-alw <msg>' to auto-allow all | (current: depth {self.depth} — {cfg['label']})[/dim]")
        self.console.print()

        session = PromptSession(history=InMemoryHistory())

        while self._running:
            try:
                text = await session.prompt_async("> ")
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break
            if not text:
                continue

            if text.lower() in ("exit", "quit"):
                if self.investigation_active:
                    agent.abort()
                self._running = False
                break
            if text.lower() == "clear":
                self.console.clear()
                continue
            if text.lower() == "review":
                if agent.inv_findings:
                    self.console.print("[cyan]Findings:[/cyan]")
                    for f in agent.inv_findings:
                        conf = f.get("confidence", "medium")
                        conf_color = {"high": "green", "medium": "yellow", "low": "dim"}.get(conf, "white")
                        self.console.print(f"  [{conf_color}][{conf.upper()}][/] {f.get('category','?')}: {f.get('detail','')[:100]}")
                else:
                    self.console.print("[dim]No findings yet.[/dim]")
                continue

            depth_match = __import__("re").match(r"^depth\s+(\d)$", text.strip().lower())
            if depth_match:
                d = int(depth_match.group(1))
                if 1 <= d <= 3:
                    self.depth = d
                    cfg = DEPTH_CONFIG[d]
                    self.agent.config["maxTurns"] = cfg["maxTurns"]
                    self.console.print(f"[green]Depth set to {d} ({cfg['label']}, max {cfg['maxTurns']} turns)[/green]")
                continue

            alw = text.strip().lower()
            if alw in ("-alw", "--allow-all"):
                agent.ctx.allow_all = not agent.ctx.allow_all
                status = "ON" if agent.ctx.allow_all else "OFF"
                agent.ctx.sandbox = "tools/custom" if agent.ctx.allow_all else None
                self.console.print(f"[green]Allow-all {status} (sandbox: tools/custom)[/green]")
                continue

            self.console.print(f"[bold]You:[/bold] {text}")
            self.investigation_active = False
            self._inv_triggered = False

            try:
                reply = await agent.send_message(text)
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                continue

            if self.investigation_active:
                self.investigation_active = False

            if reply:
                self.console.print()
                self.console.print(Markdown(reply))
                self.console.print()

        self.console.print()
        self.console.print("[yellow]Exited chat mode.[/yellow]")
