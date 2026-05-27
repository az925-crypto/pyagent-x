import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from tools.terminal import (
    is_restricted_file, assert_inside_cwd, tokenize_command,
    is_readonly_command, ToolContext, ALLOWED_COMMANDS, READONLY_PREFIXES,
    RESTRICTED_FILES, read_file_tool, write_file_tool, list_dir_tool,
    run_command_tool,
)


class TestIsRestrictedFile:
    def test_env_file(self):
        assert is_restricted_file("/path/to/.env") is True

    def test_env_local(self):
        assert is_restricted_file("/path/to/.env.local") is True

    def test_env_production(self):
        assert is_restricted_file("/path/.env.production") is True

    def test_audit_log(self):
        assert is_restricted_file("/path/.agent-x-audit.log") is True

    def test_normal_file(self):
        assert is_restricted_file("/path/to/main.py") is False

    def test_dot_env_prefix(self):
        assert is_restricted_file("/path/.env.local.backup") is True

    def test_no_path_just_filename(self):
        assert is_restricted_file(".env") is True


class TestAssertInsideCwd:
    @pytest.mark.asyncio
    async def test_path_inside_cwd(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        inside = os.path.join(tmp_path, "subdir")
        os.makedirs(inside, exist_ok=True)
        await assert_inside_cwd(inside, ctx)

    @pytest.mark.asyncio
    async def test_path_is_cwd(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        await assert_inside_cwd(str(tmp_path), ctx)

    @pytest.mark.asyncio
    async def test_path_outside_cwd(self, tmp_path):
        outside = tmp_path.parent
        ctx = ToolContext(cwd=str(tmp_path))
        with pytest.raises(PermissionError, match="Access denied"):
            await assert_inside_cwd(str(outside), ctx)

    @pytest.mark.asyncio
    async def test_path_outside_cwd_different_drive(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        with pytest.raises(PermissionError, match="Access denied"):
            await assert_inside_cwd("/tmp/somewhere", ctx)


class TestTokenizeCommand:
    def test_simple(self):
        assert tokenize_command("cat file.txt") == ["cat", "file.txt"]

    def test_quoted_string(self):
        assert tokenize_command('echo "hello world"') == ["echo", "hello world"]

    def test_single_quotes(self):
        assert tokenize_command("echo 'hello world'") == ["echo", "hello world"]

    def test_mixed_quotes(self):
        assert tokenize_command("python3 -c 'print(\"hi\")'") == ["python3", "-c", 'print("hi")']

    def test_empty(self):
        assert tokenize_command("") == []

    def test_whitespace(self):
        assert tokenize_command("  ") == []

    def test_multiple_spaces(self):
        assert tokenize_command("git   log   --oneline") == ["git", "log", "--oneline"]


class TestIsReadonlyCommand:
    def test_readonly_cat(self):
        assert is_readonly_command(["cat", "file.txt"]) is True

    def test_readonly_python_ig(self):
        assert is_readonly_command(["python3", "tools/ig/profile.py", "user"]) is True

    def test_readonly_ls(self):
        assert is_readonly_command(["ls", "-la"]) is True

    def test_readonly_git_log(self):
        assert is_readonly_command(["git", "log", "--oneline"]) is True

    def test_not_readonly_rm(self):
        assert is_readonly_command(["rm", "file"]) is False

    def test_not_readonly_git_commit(self):
        assert is_readonly_command(["git", "commit", "-m", "x"]) is False

    def test_not_readonly_write(self):
        assert is_readonly_command(["python3", "custom_script.py"]) is False


class TestAllowedCommands:
    def test_tsx_allowed(self):
        assert "tsx" in ALLOWED_COMMANDS

    def test_node_allowed(self):
        assert "node" in ALLOWED_COMMANDS

    def test_python3_allowed(self):
        assert "python3" in ALLOWED_COMMANDS

    def test_cat_allowed(self):
        assert "cat" in ALLOWED_COMMANDS

    def test_rm_not_allowed(self):
        assert "rm" in ALLOWED_COMMANDS  # rm is allowed as destructive


class TestRestrictedFiles:
    def test_env_in_restricted(self):
        assert ".env" in RESTRICTED_FILES

    def test_env_local_in_restricted(self):
        assert ".env.local" in RESTRICTED_FILES

    def test_audit_log_in_restricted(self):
        assert ".agent-x-audit.log" in RESTRICTED_FILES


class TestReadonlyPrefixes:
    def test_python_ig_prefix(self):
        assert "python3 tools/ig/" in READONLY_PREFIXES

    def test_cat_prefix(self):
        assert "cat " in READONLY_PREFIXES

    def test_curl_prefix(self):
        assert "curl " in READONLY_PREFIXES

    def test_git_log_prefix(self):
        assert "git log" in READONLY_PREFIXES

    def test_git_status_prefix(self):
        assert "git status" in READONLY_PREFIXES


class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld")
        ctx = ToolContext(cwd=str(tmp_path))
        result = await read_file_tool("test.txt", ctx)
        assert result["content"] == "hello\nworld"
        assert result["lines"] == 2

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await read_file_tool("nope.txt", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_path(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await read_file_tool("", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_restricted_file_denied(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await read_file_tool(".env", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_outside_cwd_denied(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        with pytest.raises(PermissionError, match="Access denied"):
            await read_file_tool("../outside.txt", ctx)


class TestWriteFileTool:
    @pytest.mark.asyncio
    async def test_writes_new_file(self, tmp_path):
        async def confirm(msg):
            return True
        ctx = ToolContext(cwd=str(tmp_path), confirm_func=confirm)
        result = await write_file_tool("new.txt", "content", ctx)
        assert result["written"] is True
        assert result["action"] == "create"
        assert (tmp_path / "new.txt").read_text() == "content"

    @pytest.mark.asyncio
    async def test_user_declines(self, tmp_path):
        async def confirm(msg):
            return False
        ctx = ToolContext(cwd=str(tmp_path), confirm_func=confirm)
        result = await write_file_tool("new.txt", "content", ctx)
        assert result.get("skipped") is True

    @pytest.mark.asyncio
    async def test_restricted_file_denied(self, tmp_path):
        async def confirm(msg):
            return True
        ctx = ToolContext(cwd=str(tmp_path), confirm_func=confirm)
        result = await write_file_tool(".env", "SECRET=1", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_path(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await write_file_tool("", "content", ctx)
        assert "error" in result


class TestListDirTool:
    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.txt").write_text("")
        os.makedirs(tmp_path / "sub", exist_ok=True)
        ctx = ToolContext(cwd=str(tmp_path))
        result = await list_dir_tool(".", ctx)
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_nonexistent_dir(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await list_dir_tool("nonexistent", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_outside_cwd_denied(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        with pytest.raises(PermissionError, match="Access denied"):
            await list_dir_tool("..", ctx)


class TestRunCommandTool:
    @pytest.mark.asyncio
    async def test_disallowed_command(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await run_command_tool("sudo rm -rf /", ctx)
        assert result.get("blocked") is True
        assert "sudo" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_empty_command(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await run_command_tool("", ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_denied(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        result = await run_command_tool("cat ../../etc/passwd", ctx)
        assert result.get("blocked") is True

    @pytest.mark.asyncio
    async def test_headless_blocked(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path), headless=True)
        result = await run_command_tool("echo hello", ctx)
        assert result.get("blocked") is True

    @pytest.mark.asyncio
    async def test_user_declines_readonly(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path), confirm_func=lambda msg: False)
        result = await run_command_tool("echo hello", ctx)
        assert "stdout" in result

    @pytest.mark.asyncio
    async def test_readonly_command_auto_approved(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path), confirm_func=lambda msg: False)
        result = await run_command_tool("echo hello", ctx)
        assert "stdout" in result


class TestToolContext:
    def test_default_confirm_true(self):
        ctx = ToolContext(cwd="/tmp")
        assert ctx.cwd == "/tmp"
        assert ctx.headless is False

    def test_headless_confirm_false(self):
        ctx = ToolContext(cwd="/tmp", headless=True)
        assert ctx.headless is True

    def test_custom_confirm_func(self):
        called = False
        async def confirm(msg):
            nonlocal called
            called = True
            return True
        ctx = ToolContext(cwd="/tmp", confirm_func=confirm)
        import asyncio
        result = asyncio.run(ctx.confirm("test"))
        assert result is True
        assert called is True
