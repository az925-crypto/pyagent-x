import os
import json
import time
import httpx

_provider_instance = None
_provider_info = {"type": "none", "model": "none", "createdAt": 0}


def get_model() -> str:
    provider = os.environ.get("AI_PROVIDER", "gemini")
    if provider == "zen":
        return os.environ.get("ZEN_MODEL", "big-pickle")
    elif provider == "openrouter":
        return os.environ.get("OPENROUTER_MODEL", "opencode/big-pickle")
    else:
        return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_provider_info() -> dict:
    return dict(_provider_info)


def reset_provider():
    global _provider_instance, _provider_info
    _provider_instance = None
    _provider_info = {"type": "none", "model": "none", "createdAt": 0}


def recreate_provider():
    from dotenv import load_dotenv
    load_dotenv(override=True)
    reset_provider()
    return create_provider()


def create_provider():
    global _provider_instance, _provider_info
    if _provider_instance:
        return _provider_instance

    provider_type = os.environ.get("AI_PROVIDER", "gemini")
    model = get_model()

    if provider_type == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")
        _provider_instance = OpenAICompatibleClient(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            name="OpenRouter",
        )
    elif provider_type == "zen":
        api_key = os.environ.get("ZEN_API_KEY")
        if not api_key:
            raise ValueError(
                "ZEN_API_KEY environment variable is required (get one at https://opencode.ai/auth)"
            )
        _provider_instance = OpenAICompatibleClient(
            base_url="https://opencode.ai/zen/v1",
            api_key=api_key,
            name="Zen",
        )
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        _provider_instance = GeminiClient(api_key=api_key)

    _provider_info = {"type": provider_type, "model": model, "createdAt": int(time.time() * 1000)}
    return _provider_instance


class FunctionCallResult:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class GenerateContentResult:
    def __init__(self, text: str = "", function_calls: list[FunctionCallResult] | None = None, reasoning_content: str = ""):
        self.text = text
        self.function_calls = function_calls or []
        self.reasoning_content = reasoning_content


class AIClient:
    async def generate_content(self, model: str, contents: list, system_instruction: str = "", tools: list | None = None, config: dict | None = None) -> GenerateContentResult:
        raise NotImplementedError

    async def generate_content_stream(self, model: str, contents: str, system_instruction: str = "", on_token=None, extra_config: dict | None = None) -> str:
        raise NotImplementedError


class GeminiClient(AIClient):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _convert_contents(self, contents: list) -> list:
        result = []
        for msg in contents:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            converted_parts = []
            for part in parts:
                if "text" in part:
                    converted_parts.append({"text": part["text"]})
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    converted_parts.append({
                        "functionCall": {
                            "name": fc["name"],
                            "args": fc.get("args", {}),
                        }
                    })
                elif "functionResponse" in part:
                    fr = part["functionResponse"]
                    converted_parts.append({
                        "functionResponse": {
                            "name": fr["name"],
                            "response": fr.get("response", {}),
                        }
                    })
            result.append({"role": "user" if role == "tool" else role, "parts": converted_parts})
        return result

    def _convert_tools(self, tools: list | None) -> list | None:
        if not tools:
            return None
        declarations = []
        for tool in tools:
            for fd in tool.get("functionDeclarations", []):
                declarations.append({
                    "name": fd["name"],
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {}),
                })
        return [{"functionDeclarations": declarations}] if declarations else None

    async def generate_content(self, model: str, contents: list, system_instruction: str = "", tools: list | None = None, config: dict | None = None) -> GenerateContentResult:
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        body = {"contents": self._convert_contents(contents)}
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools
        if config:
            body.setdefault("generationConfig", {})
            if "temperature" in config:
                body["generationConfig"]["temperature"] = config["temperature"]
            if "maxOutputTokens" in config:
                body["generationConfig"]["maxOutputTokens"] = config["maxOutputTokens"]
            if "responseMimeType" in config:
                body["generationConfig"]["responseMimeType"] = config["responseMimeType"]

        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(url, json=body)
            if not res.is_success:
                raise RuntimeError(f"Gemini API error {res.status_code}: {res.text}")

        data = res.json()
        candidate = (data.get("candidates") or [{}])[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        text = ""
        function_calls = []
        reasoning = ""

        for part in parts:
            if "text" in part:
                text += part["text"]
            if "functionCall" in part:
                fc = part["functionCall"]
                function_calls.append(FunctionCallResult(fc["name"], fc.get("args", {})))
            if "reasoningContent" in part:
                reasoning += part["reasoningContent"]

        return GenerateContentResult(
            text=text,
            function_calls=function_calls,
            reasoning_content=reasoning,
        )

    async def generate_content_stream(self, model: str, contents: str, system_instruction: str = "", on_token=None, extra_config: dict | None = None) -> str:
        url = f"{self.base_url}/models/{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        body = {
            "contents": [{"role": "user", "parts": [{"text": contents}]}]
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if extra_config:
            body.setdefault("generationConfig", {})
            if "responseMimeType" in extra_config:
                body["generationConfig"]["responseMimeType"] = extra_config["responseMimeType"]

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, json=body) as res:
                if not res.is_success:
                    raise RuntimeError(f"Gemini API error {res.status_code}")
                full = ""
                async for line in res.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if "text" in part:
                                        full += part["text"]
                                        if on_token:
                                            on_token(part["text"])
                        except json.JSONDecodeError:
                            pass
                return full


class OpenAICompatibleClient(AIClient):
    def __init__(self, base_url: str, api_key: str, name: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name

    def _convert_contents(self, contents: list) -> list:
        messages = []
        call_id_queue: list[str] = []
        for msg in contents:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            text_parts = [p["text"] for p in parts if "text" in p]
            function_call_parts = [p for p in parts if "functionCall" in p]
            function_response_parts = [p for p in parts if "functionResponse" in p]

            if function_call_parts:
                tool_calls = []
                for i, p in enumerate(function_call_parts):
                    fc = p["functionCall"]
                    tool_call_id = f"call_{fc['name']}_{len(call_id_queue)}"
                    call_id_queue.append(tool_call_id)
                    tool_calls.append({
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    })
                m = {"role": "assistant", "tool_calls": tool_calls}
                if msg.get("reasoningContent"):
                    m["reasoning_content"] = msg["reasoningContent"]
                messages.append(m)
            elif function_response_parts:
                for p in function_response_parts:
                    fr = p["functionResponse"]
                    tool_call_id = call_id_queue.pop(0) if call_id_queue else f"call_{fr['name']}_0"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(fr.get("response", {})),
                    })
            elif text_parts:
                content = "\n".join(text_parts)
                m = {"role": "assistant" if role == "model" else role, "content": content}
                if msg.get("reasoningContent"):
                    m["reasoning_content"] = msg["reasoningContent"]
                messages.append(m)
        return messages

    def _convert_tools(self, tools: list | None) -> list | None:
        if not tools or not tools[0].get("functionDeclarations"):
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": fd["name"],
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {}),
                },
            }
            for fd in tools[0]["functionDeclarations"]
        ]

    async def generate_content(self, model: str, contents: list, system_instruction: str = "", tools: list | None = None, config: dict | None = None) -> GenerateContentResult:
        messages = self._convert_contents(contents)
        converted_tools = self._convert_tools(tools)

        if system_instruction:
            messages.insert(0, {"role": "system", "content": system_instruction})
        body = {"model": model, "messages": messages}
        body["temperature"] = (config or {}).get("temperature", 0.7)
        max_tokens = (config or {}).get("maxOutputTokens")
        if max_tokens:
            body["max_tokens"] = max_tokens
        if converted_tools:
            body["tools"] = converted_tools
        if (config or {}).get("responseMimeType") == "application/json":
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=body,
            )
            if not res.is_success:
                raise RuntimeError(f"{self.name} API error {res.status_code}: {res.text}")

        data = res.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})

        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        function_calls = []
        for tc in message.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            function_calls.append(FunctionCallResult(tc["function"]["name"], args))

        return GenerateContentResult(
            text=text,
            function_calls=function_calls,
            reasoning_content=reasoning,
        )

    async def generate_content_stream(self, model: str, contents: str, system_instruction: str = "", on_token=None, extra_config: dict | None = None) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": contents})

        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "stream": True,
        }
        if extra_config:
            if extra_config.get("responseMimeType") == "application/json":
                body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=body,
            ) as res:
                if not res.is_success:
                    raise RuntimeError(f"{self.name} API error {res.status_code}")
                full = ""
                async for line in res.aiter_lines():
                    if line.startswith("data: "):
                        chunk_data = line[6:]
                        if chunk_data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(chunk_data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full += content
                                if on_token:
                                    on_token(content)
                        except json.JSONDecodeError:
                            pass
                return full
