import os
import sys
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings

from agent.provider import create_provider, get_model, get_provider_info, recreate_provider
from agent.shared import analyze_with_ai_stream
from tools.orchestrator import run_ig, run_sherlock, run_scan, run_ig_followers, run_ig_following, run_ig_media, run_ig_download

console = Console()
COMMANDS = ["ig", "similar", "scan", "followers", "following", "media", "download", "chat", "reconnect", "help", "clear", "exit"]

_ai = None
_chat_agent = None
_invest_findings = []
_invest_entities = 0
_invest_depth = 2


def get_ai():
    global _ai
    if _ai is None:
        _ai = create_provider()
    return _ai


def print_banner():
    banner = """
  █████╗  ██████╗ ███████╗███╗   ██╗████████╗    ██╗  ██╗
 ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝    ╚██╗██╔╝
 ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║        ╚███╔╝
 ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║        ██╔██╗
 ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║       ██╔╝ ██╗
 ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝       ╚═╝  ╚═╝
  Tools OSINT AI Base — Author: zaaam
"""
    console.print(f"[bold blue]{banner}[/bold blue]")


def show_help():
    table = Table(box=box.ROUNDED, title="Commands")
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    cmds = [
        ("ig <user>", "Instagram profile + AI analysis"),
        ("similar <user>", "Cross-platform username search"),
        ("scan <target>", "DNS/GeoIP + AI analysis"),
        ("followers <user>", "Instagram followers list"),
        ("following <user>", "Instagram following list"),
        ("media <user> [n]", "Instagram posts + comments"),
        ("download <user> [n]", "Download Instagram media"),
        ("chat", "Agentic AI mode"),
        ("reconnect", "Reload AI provider from .env"),
        ("clear", "Clear screen"),
        ("exit", "Exit"),
    ]
    for cmd, desc in cmds:
        table.add_row(cmd, desc)
    console.print(table)


async def cmd_ig(username: str):
    ai = get_ai()
    with console.status(f"[bold cyan]Fetching Instagram profile @{username}...", spinner="dots"):
        result = await run_ig(username)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    data = result.get("data", {})
    profile = data.get("profile", {})
    if not profile:
        console.print("[red]No profile data returned[/red]")
        return
    console.print(f"[green]Profile: [bold]{profile.get('fullName')}[/bold] (@{profile.get('username')})[/green]")
    console.print(f"  Followers: {profile.get('followerCount')}  Following: {profile.get('followingCount')}")
    if profile.get("publicEmail"):
        console.print(f"  Email: {profile['publicEmail']}")
    if profile.get("externalUrl"):
        console.print(f"  URL: {profile['externalUrl']}")
    if profile.get("biography"):
        console.print(f"  Bio: {profile['biography'][:180]}")
    followers = data.get("followerList", [])
    following = data.get("followingList", [])
    if followers:
        console.print(f"  Followers ({len(followers)} shown):")
        for f in followers[:10]:
            console.print(f"    @{f.get('username')}  {f.get('fullName', '')}{' ✓' if f.get('isVerified') else ''}")
        if len(followers) > 10:
            console.print(f"    ... +{len(followers)-10} more")
    if following:
        console.print(f"  Following ({len(following)} shown):")
        for f in following[:10]:
            console.print(f"    @{f.get('username')}  {f.get('fullName', '')}{' ✓' if f.get('isVerified') else ''}")
        if len(following) > 10:
            console.print(f"    ... +{len(following)-10} more")
    console.print(f"[bold cyan]AI analysis for @{username}:[/bold cyan]")
    prompt = f"Intelligence analysis for @{username}.\nData: {json.dumps(data, indent=2)}\nReturn JSON with fields: username, aiBioAnalysis, followingAnalysis, threatOrRiskLevel"
    response = await analyze_with_ai_stream(ai, prompt, on_token=lambda t: console.print(t, end=""))
    print()
    try:
        parsed = json.loads(response)
        console.print(f"[yellow]Threat:[/yellow] {parsed.get('threatOrRiskLevel', 'N/A')}")
        console.print(f"[yellow]Bio:[/yellow] {str(parsed.get('aiBioAnalysis', 'N/A'))[:160]}")
        console.print(f"[yellow]Network:[/yellow] {str(parsed.get('followingAnalysis', 'N/A'))[:160]}")
    except Exception:
        console.print(response)


async def cmd_similar(username: str):
    with console.status(f"[bold cyan]Checking username @{username} across platforms...", spinner="dots"):
        result = await run_sherlock(username)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    platforms = result.get("data", {}).get("foundPlatforms", [])
    console.print(f"[green]Found on {len(platforms)} platforms:[/green]")
    for p in platforms:
        console.print(f"  [cyan]✓[/cyan] {p}")
    if not platforms:
        console.print("  [dim]No platforms found[/dim]")


async def cmd_scan(target: str):
    with console.status(f"[bold cyan]Scanning {target}...", spinner="dots"):
        result = await run_scan(target)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Scan failed')}[/red]")
        return
    data = result.get("data", {})
    ips = data.get("resolvedIPs", [])
    geo = data.get("geoData", {})
    if ips:
        console.print(f"[green]Resolved IPs: {', '.join(ips)}[/green]")
    if geo.get("organization_name") or geo.get("organization"):
        org = geo.get("organization_name") or geo.get("organization", "")
        loc = f", {geo.get('city', '')}" if geo.get("city") else ""
        country = f", {geo.get('country', '')}" if geo.get("country") else ""
        console.print(f"  [cyan]Org:[/cyan] {org}{loc}{country}")
    if geo.get("asn"):
        console.print(f"  [cyan]ASN:[/cyan] {geo['asn']}")


async def cmd_followers(username: str):
    with console.status(f"[bold cyan]Fetching followers of @{username}...", spinner="dots"):
        result = await run_ig_followers(username)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    data = result.get("data", {})
    total = data.get("total_followers", 0)
    followers = data.get("followers", [])
    console.print(f"[green]Total followers: {total}[/green]")
    for f in followers:
        priv = " 🔒" if f.get("is_private") else ""
        console.print(f"  @{f.get('username')}  {f.get('full_name', '')}{priv}")


async def cmd_following(username: str):
    with console.status(f"[bold cyan]Fetching following of @{username}...", spinner="dots"):
        result = await run_ig_following(username)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    data = result.get("data", {})
    total = data.get("total_following", 0)
    following = data.get("following", [])
    console.print(f"[green]Total following: {total}[/green]")
    for f in following:
        priv = " 🔒" if f.get("is_private") else ""
        console.print(f"  @{f.get('username')}  {f.get('full_name', '')}{priv}")


async def cmd_media(username: str, amount: int = 5):
    with console.status(f"[bold cyan]Fetching {amount} posts of @{username}...", spinner="dots"):
        result = await run_ig_media(username, amount)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    posts = result.get("data", {}).get("posts", [])
    labels = {1: "photo", 2: "video", 8: "album"}
    console.print(f"[green]Posts: {len(posts)}[/green]")
    for post in posts:
        label = labels.get(post.get("media_type"), "?")
        console.print(f"  [{label}] {post.get('code')}  ❤ {post.get('like_count')}  💬 {post.get('comment_count')}")
        if post.get("caption"):
            console.print(f"  {post['caption'][:200]}")
        comments = post.get("comments", [])
        for c in comments[:3]:
            console.print(f"  @{c.get('username')}: {str(c.get('text', ''))[:100]}")
        if len(comments) > 3:
            console.print(f"  ... +{len(comments)-3} more comments")


async def cmd_download(username: str, amount: int = 5):
    with console.status(f"[bold cyan]Downloading {amount} media of @{username}...", spinner="dots"):
        result = await run_ig_download(username, amount)
    if not result.get("success"):
        console.print(f"[red]Error: {result.get('error', 'Tool failed')}[/red]")
        return
    data = result.get("data", {})
    items = data.get("items", [])
    console.print(f"[green]Downloaded {data.get('total_downloaded')} files → {data.get('download_dir')}[/green]")
    for item in items:
        if item.get("download_error"):
            console.print(f"[red]  {item.get('code')}: {item['download_error']}[/red]")
        elif item.get("download_path"):
            console.print(f"  {item.get('code')} → {item['download_path']}")
        elif item.get("download_paths"):
            console.print(f"  {item.get('code')} → {', '.join(item['download_paths'])}")


async def cmd_chat():
    global _invest_findings, _invest_entities, _chat_agent
    console.print("[yellow]Chat mode — type a target to investigate. Type 'exit' to quit.[/yellow]")
    console.print()
    from agent.runtime import create_agent, ToolContext
    from cli_ui_investigation import InvestigationUI

    async def confirm_handler(msg):
        console.print(f"[yellow]Confirm: {msg}[/yellow]")
        ans = await asyncio.to_thread(input, "  (y/N/all): ")
        ans = ans.strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("all", "a"):
            return "ALLOW_ALL"
        return False

    ctx = ToolContext(cwd=os.getcwd(), confirm_func=confirm_handler, headless=False)
    agent = create_agent(ai=get_ai(), ctx=ctx, callbacks={})
    _chat_agent = agent

    ui = InvestigationUI(agent, console)
    await ui.run()

    _chat_agent = None


async def cmd_reconnect():
    global _ai, _chat_agent
    _ai = recreate_provider()
    info = get_provider_info()
    console.print(f"[green]Provider reloaded: {info['type']} / {info['model']}[/green]")


async def main_loop():
    global _ai
    print_banner()
    console.print(f"[dim]Provider: {get_provider_info()['type']} / Model: {get_model()}[/dim]")
    console.print()

    bindings = KeyBindings()

    @bindings.add("c-r")
    async def _(event):
        event.app.current_buffer.text = "reconnect"
        event.app.current_buffer.validate_and_handle()

    @bindings.add("c-l")
    async def _(event):
        os.system("clear" if os.name == "posix" else "cls")
        print_banner()
        console.print(f"[dim]Provider: {get_provider_info()['type']} / Model: {get_model()}[/dim]")
        console.print()

    completer = WordCompleter(COMMANDS, ignore_case=True)
    session = PromptSession(history=InMemoryHistory(), completer=completer, key_bindings=bindings)

    while True:
        try:
            text = await session.prompt_async("agent-x@osint:~$ ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break
        if not text.strip():
            continue

        console.print(f"  $ {text}")
        parts = text.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("exit", "quit"):
            console.print("Bye!")
            break
        elif cmd == "clear":
            os.system("clear" if os.name == "posix" else "cls")
            print_banner()
        elif cmd == "help":
            show_help()
        elif cmd == "ig":
            if args:
                await cmd_ig(args[0])
            else:
                console.print("[red]usage: ig <username>[/red]")
        elif cmd == "similar":
            if args:
                await cmd_similar(args[0])
            else:
                console.print("[red]usage: similar <username>[/red]")
        elif cmd == "scan":
            if args:
                await cmd_scan(args[0])
            else:
                console.print("[red]usage: scan <target>[/red]")
        elif cmd == "followers":
            if args:
                await cmd_followers(args[0])
            else:
                console.print("[red]usage: followers <username>[/red]")
        elif cmd == "following":
            if args:
                await cmd_following(args[0])
            else:
                console.print("[red]usage: following <username>[/red]")
        elif cmd == "media":
            if args:
                n = int(args[1]) if len(args) > 1 else 5
                await cmd_media(args[0], n)
            else:
                console.print("[red]usage: media <username> [n][/red]")
        elif cmd == "download":
            if args:
                n = int(args[1]) if len(args) > 1 else 5
                await cmd_download(args[0], n)
            else:
                console.print("[red]usage: download <username> [n][/red]")
        elif cmd == "chat":
            await cmd_chat()
        elif cmd == "reconnect":
            await cmd_reconnect()
        else:
            console.print(f"[red]unknown command: {cmd}[/red]")


def main():
    asyncio.run(main_loop())


if __name__ == "__main__":
    # fix for Windows event loop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
