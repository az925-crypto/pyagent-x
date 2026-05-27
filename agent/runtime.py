import os
import json
import time
import asyncio
import inspect
import tempfile
from pathlib import Path
from .provider import create_provider, get_model, FunctionCallResult, GenerateContentResult
from .shared import SYSTEM_PROMPT
from .memory import add_memory, query_memories, get_memory_stats, get_all_memories
from tools.orchestrator import run_ig, run_scan, run_sherlock, run_ig_followers, run_ig_following, run_ig_media, run_ig_download
from tools.terminal import ToolContext, TERMINAL_TOOL_DEFS

MAX_HISTORY_LENGTH = 100
MAX_HISTORY_TOKENS = 100_000
DESTRUCTIVE_LIMIT = 5
DESTRUCTIVE_WINDOW_MS = 60_000
SESSION_TIMEOUT_MS = 60 * 60 * 1000
MAX_RETRIES = 2
MAX_API_RETRIES = 5
API_RETRY_BASE_DELAY = 4
IG_TOOL_NAMES = {"ig_profile", "ig_followers", "ig_following", "ig_media", "ig_download"}

AUDIT_DIR = Path(tempfile.gettempdir()) / ".agent-x"
AUDIT_LOG = AUDIT_DIR / "audit.log"


def _classify_error(e: Exception) -> dict:
    msg = str(e).lower()
    if "rate limit" in msg or "too many requests" in msg:
        return {"type": "rate_limit", "message": str(e)}
    if "timeout" in msg or "timed out" in msg:
        return {"type": "timeout", "message": str(e)}
    if "not found" in msg or "404" in msg:
        return {"type": "not_found", "message": str(e)}
    if "auth" in msg or "login" in msg or "unauthorized" in msg:
        return {"type": "auth_error", "message": str(e)}
    return {"type": "unknown", "message": str(e)}


def _sanitize_audit_args(tool_name: str, args: dict) -> dict:
    safe = dict(args)
    mask_fields = {"write_file": ["content"], "append_file": ["content"]}
    for key in mask_fields.get(tool_name, []):
        if key in safe:
            val = str(safe[key])
            safe[key] = f"[{len(val)} chars]"
    return safe


_audit_lock = asyncio.Lock()


async def _log_audit(entry: dict):
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": int(time.time() * 1000), **entry}) + "\n"
        async with _audit_lock:
            def _append():
                with open(str(AUDIT_LOG), "a", encoding="utf-8") as f:
                    f.write(line)
            await asyncio.to_thread(_append)
    except Exception as e:
        print(f"[Audit] write failed: {e}")


async def _exec_ig_profile(args: dict) -> dict:
    username = args.get("username", "")
    followers_limit = args.get("followersLimit")
    following_limit = args.get("followingLimit")
    result = await run_ig(username)
    if isinstance(result, dict) and "data" in result:
        data = result.get("data", {})
        if isinstance(data, dict):
            if followers_limit is not None:
                fl = data.get("followerList", [])
                if isinstance(fl, list) and len(fl) > int(followers_limit):
                    data["followerList"] = fl[:int(followers_limit)]
            if following_limit is not None:
                fl = data.get("followingList", [])
                if isinstance(fl, list) and len(fl) > int(following_limit):
                    data["followingList"] = fl[:int(following_limit)]
    return result


async def _exec_ig_media(args: dict) -> dict:
    username = args.get("username", "")
    amount = args.get("amount", 5)
    result = await run_ig_media(username, amount)
    if args.get("download") is True:
        dl = await run_ig_download(username, amount)
        return {"posts": result, "downloaded": dl}
    return result


OSINT_TOOL_DEFS = [
    {
        "name": "ig_profile",
        "description": "Instagram profile analysis via instagrapi. Returns profile, followers, following.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Instagram username"},
                "followersLimit": {"type": "number", "description": "Max followers count (optional)"},
                "followingLimit": {"type": "number", "description": "Max following count (optional)"},
            },
            "required": ["username"],
        },
        "execute": _exec_ig_profile,
    },
    {
        "name": "scan",
        "description": "DNS/GeoIP scan for domain, IP, or email.",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Target (domain, IP, or email)"}},
            "required": ["target"],
        },
        "execute": lambda args: run_scan(args.get("target", "")),
    },
    {
        "name": "ig_media",
        "description": "Fetch Instagram posts with comments and likers.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Instagram username"},
                "amount": {"type": "number", "description": "Number of posts (default: 5)"},
                "download": {"type": "boolean", "description": "Download media to local storage (default: false)"},
            },
            "required": ["username"],
        },
        "execute": _exec_ig_media,
    },
    {
        "name": "similar",
        "description": "Check username availability on 7 platforms (GitHub, GitLab, Reddit, TikTok, Medium, Vimeo, VK).",
        "parameters": {
            "type": "object",
            "properties": {"username": {"type": "string", "description": "Username to search"}},
            "required": ["username"],
        },
        "execute": lambda args: run_sherlock(args.get("username", "")),
    },
    {
        "name": "ig_followers",
        "description": "Get full Instagram followers list.",
        "parameters": {
            "type": "object",
            "properties": {"username": {"type": "string", "description": "Instagram username target"}},
            "required": ["username"],
        },
        "execute": lambda args: run_ig_followers(args.get("username", "")),
    },
    {
        "name": "ig_following",
        "description": "Get full Instagram following list.",
        "parameters": {
            "type": "object",
            "properties": {"username": {"type": "string", "description": "Instagram username target"}},
            "required": ["username"],
        },
        "execute": lambda args: run_ig_following(args.get("username", "")),
    },
]

def _make_investigation_tools(agent_ref):
    async def _init_investigation(args):
        target = args.get("target", "")
        agent_ref.inv_target = target
        agent_ref.inv_findings = []
        agent_ref.inv_started_at = int(time.time() * 1000)
        memories = await query_memories({"limit": 8})
        ctx_hint = ""
        if memories:
            ctx_hint = "\n[Relevant patterns from past investigations]:\n" + "\n".join(
                f"  [{m['confidence']}] {m['category']}: {m['pattern']}" for m in memories
            )
        return {"ok": True, "message": f"Investigation for '{target}' started.{ctx_hint}", "memoriesLoaded": len(memories)}

    async def _add_finding(args):
        finding = {
            "category": args.get("category", "other"),
            "detail": args.get("detail", ""),
            "source": args.get("source", "unknown"),
            "confidence": args.get("confidence", "medium"),
            "timestamp": int(time.time() * 1000),
        }
        agent_ref.inv_findings.append(finding)
        return {"ok": True, "totalFindings": len(agent_ref.inv_findings)}

    async def _get_investigation_summary(args):
        elapsed = 0
        if agent_ref.inv_started_at:
            elapsed = int((time.time() * 1000 - agent_ref.inv_started_at) / 1000)
        return {
            "target": agent_ref.inv_target or "unknown",
            "totalFindings": len(agent_ref.inv_findings),
            "findings": agent_ref.inv_findings[-20:],
            "elapsedSeconds": elapsed,
        }

    async def _save_memory(args):
        tags_str = args.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        result = await add_memory(
            category=args.get("category", "other"),
            pattern=args.get("pattern", ""),
            confidence=args.get("confidence", "medium"),
            tags=tags,
        )
        return {"ok": result.get("ok", False), "total": result.get("total", 0)}

    async def _load_memories(args):
        limit = args.get("limit", 10)
        q = {}
        if args.get("category"):
            q["category"] = args["category"]
        if args.get("tags"):
            q["tags"] = [t.strip() for t in args["tags"].split(",") if t.strip()]
        q["limit"] = limit
        memories = await query_memories(q if (q.get("category") or q.get("tags")) else {"limit": limit})
        return {"memories": memories, "total": len(memories)}

    async def _memory_stats(args):
        stats = await get_memory_stats()
        return stats

    return [
        {"name": "init_investigation", "description": "Start a new OSINT investigation for a target. Reset previous findings, auto-load relevant memories.", "parameters": {"type": "object", "properties": {"target": {"type": "string", "description": "Target investigasi (username, domain, email)"}}, "required": ["target"]}, "execute": _init_investigation},
        {"name": "add_finding", "description": "Record investigation findings.", "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "Kategori: profile | email | domain | ip | platform | connection | other"}, "detail": {"type": "string", "description": "Finding details"}, "source": {"type": "string", "description": "Sumber/tool"}, "confidence": {"type": "string", "description": "high / medium / low"}}, "required": ["category", "detail", "source"]}, "execute": _add_finding},
        {"name": "get_investigation_summary", "description": "Get active investigation summary with all findings and elapsed time.", "parameters": {"type": "object", "properties": {}}, "execute": _get_investigation_summary},
        {"name": "save_memory", "description": "Save anonymous patterns/insights from investigation to long-term memory (NO real usernames).", "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "Category"}, "pattern": {"type": "string", "description": "Pattern description (ANONYMOUS, no real usernames)"}, "confidence": {"type": "string", "description": "high / medium / low"}, "tags": {"type": "string", "description": "Tags pisah koma"}}, "required": ["category", "pattern", "confidence"]}, "execute": _save_memory},
        {"name": "load_memories", "description": "Load relevant patterns from past investigations.", "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "Filter by category (optional)"}, "tags": {"type": "string", "description": "Filter by tags, comma-separated (optional)"}, "limit": {"type": "number", "description": "Maks hasil (default 10)"}}}, "execute": _load_memories},
        {"name": "memory_stats", "description": "View saved memory statistics.", "parameters": {"type": "object", "properties": {}}, "execute": _memory_stats},
    ]

DANGEROUS_TOOLS = {"write_file", "append_file", "make_dir", "delete_file", "run_command"}


async def with_retry(tool_fn, fn_args: dict, fn_name: str, max_retries: int = MAX_RETRIES) -> dict:
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await tool_fn(fn_args)
            if isinstance(result, dict) and result.get("error"):
                err_str = str(result["error"]).lower()
                is_retryable = any(k in err_str for k in ["timeout", "rate limit", "too many", "429", "503", "500", "connection", "reset"])
                if is_retryable and attempt < max_retries:
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)
                    continue
            return result
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            is_retryable = any(k in err_str for k in ["timeout", "rate limit", "too many", "429", "503", "500", "connection", "reset"])
            if is_retryable and attempt < max_retries:
                wait = (attempt + 1) * 2
                await asyncio.sleep(wait)
                continue
            return {"error": str(e)}
    return {"error": f"Failed after {max_retries + 1} attempts: {last_error}"}


def inject_trim_summary(history: list, trimmed: list, inv_findings: list) -> str:
    if not trimmed:
        return ""
    tool_calls = set()
    results = sum(1 for m in trimmed if any("functionResponse" in p for p in m.get("parts", [])))
    texts = sum(1 for m in trimmed if any("text" in p for p in m.get("parts", [])))
    for m in trimmed:
        for p in m.get("parts", []):
            if "functionCall" in p:
                tool_calls.add(p["functionCall"]["name"])
    tools_str = f" Tools used: {', '.join(sorted(tool_calls))}." if tool_calls else ""
    findings_summary = ""
    if inv_findings:
        recent = inv_findings[-5:]
        findings_summary = " Key findings: " + "; ".join(
            f"[{f.get('category','?')}] {f.get('detail','')[:100]} (via {f.get('source','?')})" for f in recent
        ) + "."
    summary = f"[Context trimmed: {len(trimmed)} messages ({results} results, {texts} texts).{tools_str}{findings_summary} Continuing with remaining context.]"
    history.insert(1, {"role": "user", "parts": [{"text": summary}]})
    return summary


def _to_tool_def(t):
    return {
        "name": t["name"],
        "description": t["description"],
        "parameters": t["parameters"],
    }


def _is_retryable_api_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ["timeout", "rate limit", "too many", "429", "503", "500", "connection", "reset", "service unavailable", "deadline", "transport", "unavailable", "internal"])


def _fmt_api_error(e: Exception) -> str:
    import httpx
    name = type(e).__name__
    msg = str(e)
    if not msg:
        msg = repr(e)
    if isinstance(e, httpx.ConnectError):
        msg = "Tidak bisa terhubung ke server AI. Periksa koneksi internet atau jika provider AI sedang down."
    elif isinstance(e, httpx.TimeoutException):
        msg = "Koneksi timeout. Server AI terlalu lambat merespon."
    elif isinstance(e, httpx.RemoteProtocolError):
        msg = "Koneksi terputus oleh server. Coba lagi."
    return f"[{name}] {msg}"


def _estimate_tokens(msg: dict) -> int:
    if "text" in msg:
        return max(1, int(len(str(msg["text"])) * 0.4))
    if "functionCall" in msg:
        return max(1, int(len(json.dumps(msg["functionCall"]["args"])) * 0.3))
    if "functionCalls" in msg:
        return sum(max(1, int(len(json.dumps(fc["args"])) * 0.3)) for fc in msg["functionCalls"])
    if "functionResponse" in msg:
        return max(1, int(len(json.dumps(msg["functionResponse"]["response"])) * 0.3))
    return 1


class Agent:
    def __init__(self, ai, model: str, ctx: ToolContext, callbacks=None, config=None):
        self.ai = ai
        self.model = model
        self.ctx = ctx
        self.callbacks = callbacks or {}
        self.config = config or {}
        self.history = []
        self.inv_target = None
        self.inv_findings = []
        self.inv_started_at = 0
        self.aborted = False

        self.inv_tools = _make_investigation_tools(self)
        self.all_tools = TERMINAL_TOOL_DEFS + OSINT_TOOL_DEFS + self.inv_tools

    def abort(self):
        self.aborted = True

    async def send_message(self, user_input: str) -> str:
        self.history.append({"role": "user", "parts": [{"text": user_input}]})
        turns = 0
        max_turns = self.config.get("maxTurns", 50)
        session_timeout_ms = self.config.get("sessionTimeoutMs", SESSION_TIMEOUT_MS)
        session_start = int(time.time() * 1000)
        destructive_timestamps = []
        cross_turn_calls = []

        while turns < max_turns:
            if self.aborted:
                return "Investigation aborted by user."

            if int(time.time() * 1000) - session_start > session_timeout_ms:
                elapsed = (int(time.time() * 1000) - session_start) // 1000
                return f"Session timeout after {elapsed}s."

            turns += 1

            # Two-phase history trim (matching TS logic)
            trimmed = []
            # Phase 1: By message count
            if len(self.history) > MAX_HISTORY_LENGTH:
                target_len = MAX_HISTORY_LENGTH - 1
                trimmed = self.history[1:len(self.history) - target_len + 1]
                self.history = [self.history[0]] + self.history[len(self.history) - target_len + 1:]
                inject_trim_summary(self.history, trimmed, self.inv_findings)
            else:
                # Phase 2: By token count
                total_tokens = sum(_estimate_tokens(m) for m in self.history)
                if total_tokens > MAX_HISTORY_TOKENS:
                    tokens_to_remove = total_tokens - MAX_HISTORY_TOKENS
                    remove_count = 0
                    for i in range(1, len(self.history)):
                        if tokens_to_remove <= 0:
                            break
                        tokens_to_remove -= _estimate_tokens(self.history[i])
                        remove_count += 1
                    if remove_count > 0:
                        trimmed = self.history[1:1 + remove_count]
                        self.history = [self.history[0]] + self.history[1 + remove_count:]
                        inject_trim_summary(self.history, trimmed, self.inv_findings)
                    elif len(self.history) == 1 and total_tokens > MAX_HISTORY_TOKENS:
                        max_chars = int(MAX_HISTORY_TOKENS * 2.5 * 0.75)
                        msg = self.history[0]
                        text_parts = [p for p in msg.get("parts", []) if "text" in p]
                        if text_parts and len(text_parts[0].get("text", "")) > max_chars:
                            original = len(text_parts[0]["text"])
                            text_parts[0]["text"] = text_parts[0]["text"][:max_chars] + f"\n\n[System: message trimmed from {original} to {max_chars} chars due to context budget.]"
            function_declarations = [_to_tool_def(t) for t in self.all_tools]

            api_success = False
            for api_attempt in range(MAX_API_RETRIES + 1):
                try:
                    result = await self.ai.generate_content(
                        model=self.model,
                        contents=self.history,
                        system_instruction=SYSTEM_PROMPT,
                        tools=[{"functionDeclarations": function_declarations}],
                        config={"temperature": 0.7},
                    )
                    api_success = True
                    break
                except Exception as e:
                    if api_attempt < MAX_API_RETRIES and _is_retryable_api_error(e):
                        wait = (api_attempt + 1) * API_RETRY_BASE_DELAY
                        if self.callbacks.get("onToolResult"):
                            self.callbacks["onToolResult"]("_ai_retry", {"attempt": api_attempt + 1, "max": MAX_API_RETRIES, "wait": wait}, 0)
                        await asyncio.sleep(wait)
                        continue
                    return _fmt_api_error(e)
            if not api_success:
                return "AI API sedang sibuk atau tidak terjangkau. Coba beberapa saat lagi ya."

            if not result.function_calls:
                reply = result.text
                if not reply:
                    return "[AI returned empty response]"
                msg = {"role": "model", "parts": [{"text": reply}]}
                if result.reasoning_content:
                    msg["reasoningContent"] = result.reasoning_content
                self.history.append(msg)
                return reply

            # Process function calls
            pending_calls = []
            loop_detected = False

            for fc in result.function_calls:
                fn_name = fc.name
                fn_args = fc.args
                call_key = json.dumps({"name": fn_name, "args": fn_args}, sort_keys=True)

                cross_turn_calls.append({"name": fn_name, "args": call_key})
                recent3 = cross_turn_calls[-3:]
                if not loop_detected and len(recent3) == 3 and all(c["name"] == recent3[0]["name"] and c["args"] == recent3[0]["args"] for c in recent3):
                    loop_detected = True
                if loop_detected:
                    pending_calls.append({"name": fn_name, "args": fn_args, "error": "Loop detected", "skipped": True})
                    continue

                tool = next((t for t in self.all_tools if t["name"] == fn_name), None)
                if not tool:
                    pending_calls.append({"name": fn_name, "args": fn_args, "error": f'Tool "{fn_name}" not found.'})
                    continue

                if fn_name in DANGEROUS_TOOLS:
                    now = int(time.time() * 1000)
                    while destructive_timestamps and destructive_timestamps[0] < now - DESTRUCTIVE_WINDOW_MS:
                        destructive_timestamps.pop(0)
                    if len(destructive_timestamps) >= DESTRUCTIVE_LIMIT:
                        pending_calls.append({"name": fn_name, "args": fn_args, "error": f"Rate limit: max {DESTRUCTIVE_LIMIT} destructive ops per minute."})
                        continue
                    destructive_timestamps.append(now)
                    if self.ctx.headless:
                        pending_calls.append({"name": fn_name, "args": fn_args, "error": "Destructive ops disabled in headless mode."})
                        continue
                    msg = f"AI ingin: **{fn_name}**\nArgs:\n{json.dumps(fn_args, indent=2)}\nSetuju? (y/N): "
                    confirmed = await self.ctx.confirm(msg)
                    if not confirmed:
                        pending_calls.append({"name": fn_name, "args": fn_args, "error": "User declined", "skipped": True})
                        continue

                if self.callbacks.get("onToolCall"):
                    self.callbacks["onToolCall"](fn_name, fn_args)

                tool_start = time.monotonic()
                is_ig_tool = fn_name in IG_TOOL_NAMES
                try:
                    execute_fn = tool["execute"]
                    if is_ig_tool:
                        result_data = await with_retry(execute_fn, fn_args, fn_name, max_retries=MAX_RETRIES)
                    else:
                        sig = inspect.signature(execute_fn)
                        if len(sig.parameters) >= 2:
                            result_data = await execute_fn(fn_args, self.ctx)
                        else:
                            result_data = await execute_fn(fn_args)
                except Exception as e:
                    result_data = {"error": str(e)}

                duration_ms = int((time.monotonic() - tool_start) * 1000)
                if self.callbacks.get("onToolResult"):
                    self.callbacks["onToolResult"](fn_name, result_data, duration_ms)

                pending_calls.append({"name": fn_name, "args": fn_args, "result": result_data})

            if pending_calls:
                msg = {
                    "role": "model",
                    "parts": [{"functionCall": {"name": p["name"], "args": p["args"]}} for p in pending_calls],
                }
                if result.reasoning_content:
                    msg["reasoningContent"] = result.reasoning_content
                self.history.append(msg)
                pending_responses = []
                for p in pending_calls:
                    response = p.get("result", p.get("error", {}))
                    pending_responses.append({"name": p["name"], "response": response})
                self.history.append({
                    "role": "tool",
                    "parts": [{"functionResponse": r} for r in pending_responses],
                })

        return "Reached maximum iteration limit."


def create_agent(ai=None, ctx=None, callbacks=None, config=None):
    if ai is None:
        ai = create_provider()
    model = get_model()
    if ctx is None:
        ctx = ToolContext(cwd=os.getcwd())
    return Agent(ai, model, ctx, callbacks, config)
