import os
import json
import pytest
from unittest.mock import patch
from agent.provider import (
    get_model, get_provider_info, reset_provider, create_provider,
    GeminiClient, OpenAICompatibleClient,
    GenerateContentResult, FunctionCallResult,
)


class TestGetModel:
    def test_default_gemini(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini"}, clear=True):
            assert get_model() == "gemini-2.5-flash"

    def test_gemini_custom(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-2.0-pro"}):
            assert get_model() == "gemini-2.0-pro"

    def test_openrouter_default(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter"}, clear=True):
            assert get_model() == "opencode/big-pickle"

    def test_openrouter_custom(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "OPENROUTER_MODEL": "anthropic/claude-3"}):
            assert get_model() == "anthropic/claude-3"

    def test_zen_default(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "zen"}, clear=True):
            assert get_model() == "big-pickle"

    def test_zen_custom(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "zen", "ZEN_MODEL": "zen-v2"}):
            assert get_model() == "zen-v2"


class TestCreateProvider:
    def setup_method(self):
        reset_provider()

    def test_create_gemini(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}):
            provider = create_provider()
            assert isinstance(provider, GeminiClient)
            assert provider.api_key == "test-key"
            info = get_provider_info()
            assert info["type"] == "gemini"
            assert info["model"] == "gemini-2.5-flash"

    def test_create_openrouter(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "test-key"}):
            provider = create_provider()
            assert isinstance(provider, OpenAICompatibleClient)
            assert provider.name == "OpenRouter"

    def test_create_zen(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "zen", "ZEN_API_KEY": "test-key"}):
            provider = create_provider()
            assert isinstance(provider, OpenAICompatibleClient)
            assert provider.name == "Zen"

    def test_create_gemini_missing_key(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini"}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                create_provider()

    def test_create_openrouter_missing_key(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter"}, clear=True):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                create_provider()

    def test_caches_provider(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}):
            p1 = create_provider()
            p2 = create_provider()
            assert p1 is p2


class TestGeminiClientConvertContents:
    def setup_method(self):
        self.client = GeminiClient(api_key="test-key")

    def test_text_message(self):
        contents = [{"role": "user", "parts": [{"text": "hello"}]}]
        result = self.client._convert_contents(contents)
        assert result == [{"role": "user", "parts": [{"text": "hello"}]}]

    def test_function_call(self):
        contents = [{
            "role": "model",
            "parts": [{"functionCall": {"name": "test_fn", "args": {"key": "val"}}}],
        }]
        result = self.client._convert_contents(contents)
        assert result[0]["role"] == "model"
        assert result[0]["parts"][0]["functionCall"]["name"] == "test_fn"

    def test_function_response(self):
        contents = [{
            "role": "tool",
            "parts": [{"functionResponse": {"name": "test_fn", "response": {"ok": True}}}],
        }]
        result = self.client._convert_contents(contents)
        assert result[0]["role"] == "user"
        assert result[0]["parts"][0]["functionResponse"]["name"] == "test_fn"

    def test_mixed_parts(self):
        contents = [{
            "role": "model",
            "parts": [
                {"text": "Let me check"},
                {"functionCall": {"name": "scan", "args": {"target": "x"}}},
            ],
        }]
        result = self.client._convert_contents(contents)
        assert len(result[0]["parts"]) == 2


class TestGeminiClientConvertTools:
    def setup_method(self):
        self.client = GeminiClient(api_key="test-key")

    def test_convert_tools_basic(self):
        tools = [{"functionDeclarations": [
            {"name": "test_fn", "description": "A test", "parameters": {"type": "object"}},
        ]}]
        result = self.client._convert_tools(tools)
        assert result == [{"functionDeclarations": [
            {"name": "test_fn", "description": "A test", "parameters": {"type": "object"}},
        ]}]

    def test_convert_tools_none(self):
        assert self.client._convert_tools(None) is None

    def test_convert_tools_empty(self):
        assert self.client._convert_tools([]) is None


class TestOpenAIClientConvertContents:
    def setup_method(self):
        self.client = OpenAICompatibleClient(base_url="https://test.ai/v1", api_key="test", name="Test")

    def test_text_message(self):
        contents = [{"role": "user", "parts": [{"text": "hello"}]}]
        result = self.client._convert_contents(contents)
        assert result == [{"role": "user", "content": "hello"}]

    def test_model_role_to_assistant(self):
        contents = [{"role": "model", "parts": [{"text": "I think so"}]}]
        result = self.client._convert_contents(contents)
        assert result == [{"role": "assistant", "content": "I think so"}]

    def test_function_call(self):
        contents = [{
            "role": "model",
            "parts": [{"functionCall": {"name": "scan", "args": {"target": "x"}}}],
        }]
        result = self.client._convert_contents(contents)
        assert result[0]["role"] == "assistant"
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "scan"

    def test_function_response(self):
        contents = [{
            "role": "tool",
            "parts": [{"functionResponse": {"name": "scan", "response": {"ok": True}}}],
        }]
        result = self.client._convert_contents(contents)
        assert result[0]["role"] == "tool"
        assert result[0]["content"] == json.dumps({"ok": True})

    def test_reasoning_content(self):
        contents = [{"role": "model", "parts": [{"text": "thinking..."}], "reasoningContent": "step by step"}]
        result = self.client._convert_contents(contents)
        assert result[0]["reasoning_content"] == "step by step"


class TestOpenAIClientConvertTools:
    def setup_method(self):
        self.client = OpenAICompatibleClient(base_url="https://test.ai/v1", api_key="test", name="Test")

    def test_basic(self):
        tools = [{"functionDeclarations": [
            {"name": "fn1", "description": "desc", "parameters": {"type": "object"}},
        ]}]
        result = self.client._convert_tools(tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "fn1"

    def test_none(self):
        assert self.client._convert_tools(None) is None

    def test_empty_declarations(self):
        assert self.client._convert_tools([{"functionDeclarations": []}]) is None


class TestGenerateContentResult:
    def test_defaults(self):
        r = GenerateContentResult()
        assert r.text == ""
        assert r.function_calls == []
        assert r.reasoning_content == ""

    def test_with_content(self):
        fc = FunctionCallResult("test", {"a": 1})
        r = GenerateContentResult(text="hello", function_calls=[fc], reasoning_content="thinking")
        assert r.text == "hello"
        assert len(r.function_calls) == 1
        assert r.function_calls[0].name == "test"
        assert r.function_calls[0].args == {"a": 1}
        assert r.reasoning_content == "thinking"

    def test_function_call_result_props(self):
        fc = FunctionCallResult("scan", {"target": "x"})
        assert fc.name == "scan"
        assert fc.args == {"target": "x"}
