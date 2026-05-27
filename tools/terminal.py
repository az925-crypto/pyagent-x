import os
import re
import asyncio
from pathlib import Path

ALLOWED_COMMANDS = {
    "cat", "ls", "grep", "find", "head", "tail", "sort", "uniq", "wc",
    "curl", "wget", "python3", "python", "node", "tsx",
    "echo", "date", "whoami", "hostname",
    "ping", "nslookup", "dig",
    "mkdir", "cp", "mv", "rm", "chmod",
    "git", "npm", "npx",
}

READONLY_PREFIXES = [
    "python3 tools/ig/",
    "python3 tools/custom/",
    "cat ", "ls ", "head ", "tail ", "sort ", "uniq ", "wc ",
    "echo ", "date ", "whoami", "hostname",
    "ping ", "nslookup ", "dig ",
    "curl ", "wget ",
    "git log", "git status", "git diff", "git show", "git branch",
]

RESTRICTED_FILES = [
    ".env", ".env.local", ".env.production", ".env.development",
    ".agent-x-audit.log",
]


SANDBOX_DIR = "tools/custom"


class ToolContext:
    def __init__(self, cwd: str, confirm_func=None, headless: bool = False):
        self.cwd = cwd
        self.confirm_func = confirm_func or (lambda msg: "ALLOW_ALL" if headless else True)
        self.headless = headless
        self.allow_all = False
        self._sandbox = None

    @property
    def sandbox(self) -> str | None:
        return self._sandbox

    @sandbox.setter
    def sandbox(self, path: str | None):
        if path is None:
            self._sandbox = None
        else:
            resolved = os.path.realpath(os.path.join(self.cwd, path))
            self._sandbox = resolved

    async def confirm(self, msg: str) -> bool:
        if self.headless:
            return False
        if self.allow_all:
            return True
        result = await self.confirm_func(msg)
        if result == "ALLOW_ALL":
            self.allow_all = True
            return True
        return bool(result)


def is_restricted_file(resolved_path: str) -> bool:
    base = os.path.basename(resolved_path)
    if base in RESTRICTED_FILES or base.startswith(".env"):
        return True
    return False


async def assert_in_sandbox(resolved: str, ctx: ToolContext):
    if ctx.sandbox is None:
        return
    try:
        real_resolved = os.path.realpath(resolved)
    except OSError:
        parent = os.path.dirname(resolved)
        base = os.path.basename(resolved)
        try:
            real_parent = os.path.realpath(parent)
            real_resolved = os.path.join(real_parent, base)
        except OSError:
            real_resolved = os.path.abspath(resolved)
    sandbox_with_sep = ctx.sandbox if ctx.sandbox.endswith(os.sep) else ctx.sandbox + os.sep
    if real_resolved != ctx.sandbox and not real_resolved.startswith(sandbox_with_sep):
        raise PermissionError(f'Access denied: path "{real_resolved}" is outside sandbox "{ctx.sandbox}"')


async def assert_inside_cwd(resolved: str, ctx: ToolContext):
    # Resolve the resolved path with fallback if file doesn't exist
    try:
        real_resolved = os.path.realpath(resolved)
    except OSError:
        # File doesn't exist — resolve parent dir only
        parent = os.path.dirname(resolved)
        base = os.path.basename(resolved)
        try:
            real_parent = os.path.realpath(parent)
            real_resolved = os.path.join(real_parent, base)
        except OSError:
            real_resolved = os.path.abspath(resolved)

    # Resolve cwd with fallback if directory doesn't exist
    try:
        real_cwd = os.path.realpath(ctx.cwd)
    except OSError:
        real_cwd = ctx.cwd

    cwd_with_sep = real_cwd if real_cwd.endswith(os.sep) else real_cwd + os.sep
    if real_resolved != real_cwd and not real_resolved.startswith(cwd_with_sep):
        raise PermissionError(f'Access denied: path "{real_resolved}" is outside working directory')


async def read_file_tool(file_path: str, ctx: ToolContext) -> dict:
    if not isinstance(file_path, str) or not file_path.strip():
        return {"error": "filePath must be a non-empty string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, file_path))
    await assert_inside_cwd(resolved, ctx)
    if is_restricted_file(resolved):
        return {"error": f'Access denied: "{os.path.basename(resolved)}" is a restricted file.'}
    try:
        content = await asyncio.to_thread(Path(resolved).read_text, encoding="utf-8")
        lines = content.split("\n")
        return {"summary": f"{resolved}: {len(lines)} lines, {len(content)} chars", "content": content, "lines": len(lines)}
    except Exception as e:
        return {"error": str(e)}


async def write_file_tool(file_path: str, content: str, ctx: ToolContext) -> dict:
    if not isinstance(file_path, str) or not file_path.strip():
        return {"error": "filePath must be a non-empty string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, file_path))
    await assert_inside_cwd(resolved, ctx)
    await assert_in_sandbox(resolved, ctx)
    if is_restricted_file(resolved):
        return {"error": f'Access denied: cannot write to "{os.path.basename(resolved)}".'}
    parent = os.path.dirname(resolved)
    if not os.path.exists(parent):
        await asyncio.to_thread(os.makedirs, parent, exist_ok=True)
    exists = os.path.exists(resolved)
    action = "overwrite" if exists else "create"
    ok = await ctx.confirm(f"Write {action} {resolved}? ({len(content)} chars)")
    if not ok:
        return {"skipped": True, "reason": "User declined"}
    await asyncio.to_thread(Path(resolved).write_text, content, encoding="utf-8")
    return {"written": True, "path": resolved, "action": action, "chars": len(content)}


async def list_dir_tool(dir_path: str, ctx: ToolContext) -> dict:
    if not isinstance(dir_path, str):
        return {"error": "dir_path must be a string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, dir_path))
    await assert_inside_cwd(resolved, ctx)
    try:
        entries = []
        for entry in os.scandir(resolved):
            info = {"name": entry.name, "type": "dir" if entry.is_dir() else "file", "size": None}
            if entry.is_file():
                try:
                    info["size"] = entry.stat().st_size
                except Exception:
                    pass
            entries.append(info)
        return {
            "path": resolved,
            "entries": [f'[{"DIR" if e["type"] == "dir" else "FILE"}] {e["name"]}' + (f' ({e["size"]}B)' if e["size"] is not None else "") for e in entries],
            "total": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}


async def delete_file_tool(file_path: str, ctx: ToolContext) -> dict:
    if not isinstance(file_path, str) or not file_path.strip():
        return {"error": "filePath must be a non-empty string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, file_path))
    await assert_inside_cwd(resolved, ctx)
    await assert_in_sandbox(resolved, ctx)
    if is_restricted_file(resolved):
        return {"error": f'Access denied: cannot delete "{os.path.basename(resolved)}".'}
    label = "directory" if os.path.isdir(resolved) else "file"
    ok = await ctx.confirm(f"Delete {label} {resolved}?")
    if not ok:
        return {"skipped": True, "reason": "User declined"}
    import shutil
    if os.path.isdir(resolved):
        shutil.rmtree(resolved, ignore_errors=True)
    else:
        os.remove(resolved)
    return {"deleted": True, "path": resolved, "type": label}


def tokenize_command(command: str) -> list[str]:
    tokens, current = [], ""
    in_single, in_double = False, False
    for ch in command:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == " " and not in_single and not in_double:
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def is_readonly_command(tokens: list[str]) -> bool:
    full = " ".join(tokens)
    return any(full.startswith(p) for p in READONLY_PREFIXES)


async def run_command_tool(command: str, ctx: ToolContext) -> dict:
    if not isinstance(command, str) or not command.strip():
        return {"error": "command must be a non-empty string"}
    tokens = tokenize_command(command.strip())
    if not tokens:
        return {"error": "Empty command"}
    cmd_name = tokens[0]
    if cmd_name not in ALLOWED_COMMANDS:
        return {"blocked": True, "reason": f'Command "{cmd_name}" not allowed.', "command": command}
    for token in tokens[1:]:
        parts = token.replace("\\", "/").split("/")
        if ".." in parts:
            return {"blocked": True, "reason": 'Path traversal ".." not allowed.', "command": command}
        if token.startswith("/") and not token.startswith("/usr/") and not token.startswith("/bin/") and not token.startswith("/tmp/"):
            return {"blocked": True, "reason": f'Absolute path "{token}" not allowed.', "command": command}
    if ctx.headless:
        return {"blocked": True, "reason": "Command execution disabled in headless mode."}
    if not is_readonly_command(tokens):
        ok = await ctx.confirm(f"Run command: {command}")
        if not ok:
            return {"skipped": True, "reason": "User declined"}
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd_name, *tokens[1:],
            cwd=ctx.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "command": command,
            "exitCode": proc.returncode or 0,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }
    except asyncio.TimeoutError:
        return {"command": command, "exitCode": 1, "stdout": "", "stderr": "Command timed out (30s)"}
    except Exception as e:
        return {"command": command, "exitCode": 1, "stdout": "", "stderr": str(e)}


async def grep_file_tool(pattern: str, file_path: str, ctx: ToolContext) -> dict:
    if not isinstance(pattern, str) or not pattern.strip():
        return {"error": "pattern must be a non-empty string"}
    if not isinstance(file_path, str) or not file_path.strip():
        return {"error": "filePath must be a non-empty string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, file_path))
    await assert_inside_cwd(resolved, ctx)
    if is_restricted_file(resolved):
        return {"error": f'Access denied: "{os.path.basename(resolved)}" is a restricted file.'}
    try:
        content = await asyncio.to_thread(Path(resolved).read_text, encoding="utf-8")
        lines = content.split("\n")
        matches = []
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                matches.append({"line": i, "text": line, "match": True})
        return {
            "file": resolved,
            "pattern": pattern,
            "totalLines": len(lines),
            "matches": len(matches),
            "results": matches[:50],
            "truncated": len(matches) > 50,
        }
    except re.error as e:
        return {"error": f"Invalid regex pattern: {e}"}
    except Exception as e:
        return {"error": str(e)}


async def glob_files_tool(pattern: str, ctx: ToolContext) -> dict:
    if not isinstance(pattern, str) or not pattern.strip():
        return {"error": "pattern must be a non-empty string"}
    try:
        import glob as glob_mod
        search_path = os.path.join(ctx.cwd, pattern)
        matches = await asyncio.to_thread(glob_mod.glob, search_path, recursive=True)
        results = []
        for m in sorted(matches):
            rel = os.path.relpath(m, ctx.cwd)
            results.append(rel)
        return {"pattern": pattern, "total": len(results), "results": results[:100], "truncated": len(results) > 100}
    except Exception as e:
        return {"error": str(e)}


_append_lock = asyncio.Lock()


async def append_file_tool(file_path: str, content: str, ctx: ToolContext) -> dict:
    if not isinstance(file_path, str) or not file_path.strip():
        return {"error": "filePath must be a non-empty string"}
    if not isinstance(content, str):
        return {"error": "content must be a string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, file_path))
    await assert_inside_cwd(resolved, ctx)
    await assert_in_sandbox(resolved, ctx)
    if is_restricted_file(resolved):
        return {"error": f'Access denied: cannot append to "{os.path.basename(resolved)}".'}
    if not os.path.exists(resolved):
        return {"error": f"File not found: {resolved}"}
    ok = await ctx.confirm(f"Append {len(content)} chars to {resolved}?")
    if not ok:
        return {"skipped": True, "reason": "User declined"}
    try:
        async with _append_lock:
            def _append():
                with open(resolved, "a", encoding="utf-8") as f:
                    f.write(content)
            await asyncio.to_thread(_append)
        return {"appended": True, "path": resolved, "chars": len(content)}
    except Exception as e:
        return {"error": str(e)}


async def make_dir_tool(dir_path: str, ctx: ToolContext) -> dict:
    if not isinstance(dir_path, str) or not dir_path.strip():
        return {"error": "dirPath must be a non-empty string"}
    resolved = os.path.realpath(os.path.join(ctx.cwd, dir_path))
    await assert_inside_cwd(resolved, ctx)
    try:
        await asyncio.to_thread(os.makedirs, resolved, exist_ok=True)
        return {"created": True, "path": resolved}
    except Exception as e:
        return {"error": str(e)}


async def get_cwd_tool(ctx: ToolContext) -> dict:
    return {"cwd": os.path.realpath(ctx.cwd)}


TERMINAL_TOOL_DEFS = [
    {
        "name": "read_file",
        "description": "Read contents of a file. Returns the full content and summary.",
        "parameters": {
            "type": "object",
            "properties": {"filePath": {"type": "string", "description": "Path to the file (relative to cwd)"}},
            "required": ["filePath"],
        },
        "execute": lambda args, ctx: read_file_tool(args.get("filePath", ""), ctx),
    },
    {
        "name": "list_dir",
        "description": "List files and directories in a directory.",
        "parameters": {
            "type": "object",
            "properties": {"dirPath": {"type": "string", "description": "Directory path (default: current directory)"}},
            "required": ["dirPath"],
        },
        "execute": lambda args, ctx: list_dir_tool(args.get("dirPath", "."), ctx),
    },
    {
        "name": "grep_file",
        "description": "Search for a regex pattern inside a file. Returns matching lines with line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "filePath": {"type": "string", "description": "Path to the file"},
            },
            "required": ["pattern", "filePath"],
        },
        "execute": lambda args, ctx: grep_file_tool(args.get("pattern", ""), args.get("filePath", ""), ctx),
    },
    {
        "name": "glob_files",
        "description": "Search for files matching a glob pattern (e.g. **/*.py, src/**/*.ts).",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"}},
            "required": ["pattern"],
        },
        "execute": lambda args, ctx: glob_files_tool(args.get("pattern", ""), ctx),
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to write to"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["filePath", "content"],
        },
        "execute": lambda args, ctx: write_file_tool(args.get("filePath", ""), args.get("content", ""), ctx),
    },
    {
        "name": "append_file",
        "description": "Append content to an existing file. Requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["filePath", "content"],
        },
        "execute": lambda args, ctx: append_file_tool(args.get("filePath", ""), args.get("content", ""), ctx),
    },
    {
        "name": "make_dir",
        "description": "Create a directory (and parents if needed).",
        "parameters": {
            "type": "object",
            "properties": {"dirPath": {"type": "string", "description": "Directory path to create"}},
            "required": ["dirPath"],
        },
        "execute": lambda args, ctx: make_dir_tool(args.get("dirPath", ""), ctx),
    },
    {
        "name": "delete_file",
        "description": "Delete a file or directory. Requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {"filePath": {"type": "string", "description": "Path to delete"}},
            "required": ["filePath"],
        },
        "execute": lambda args, ctx: delete_file_tool(args.get("filePath", ""), ctx),
    },
    {
        "name": "get_cwd",
        "description": "Get the current working directory path.",
        "parameters": {"type": "object", "properties": {}},
        "execute": lambda args, ctx: get_cwd_tool(ctx),
    },
    {
        "name": "run_command",
        "description": "Execute a shell command (allowlisted commands only). Requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": 'Command to execute (e.g. "python3 script.py")'}},
            "required": ["command"],
        },
        "execute": lambda args, ctx: run_command_tool(args.get("command", ""), ctx),
    },
]
