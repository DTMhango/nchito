"""Provider adapters: thin, one request each, no retries of their own (the service retries so that
every attempt is budgeted). Adapters never log prompts or keys.

- ``AnthropicAdapter``: official ``anthropic`` SDK, structured output through
  ``output_config.format`` (JSON schema), prompt caching on the stable system prefix.
- ``OpenAICompatibleAdapter``: ``/chat/completions`` on any OpenAI-compatible base URL
  (OpenRouter, a self-hosted model), ``response_format`` JSON schema (or JSON mode, or none).
- ``ClaudeCliAdapter``: ``claude -p --output-format json --json-schema``, no tools, on the PC only;
  its spend is logged as an estimate and marked not billed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anthropic
import httpx

from app.llm.client import LLMError
from app.llm.render import parse_json_text

ProviderName = Literal["anthropic", "openai_compatible", "claude_cli"]


@dataclass(frozen=True)
class Credentials:
    api_key: str | None = None
    base_url: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # keys never reach logs or tracebacks
        return f"Credentials(base_url={self.base_url!r}, api_key={'***' if self.api_key else None})"


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    system: str
    turns: list[tuple[Literal["user", "assistant"], str]]
    json_schema: dict[str, Any]
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class ProviderReply:
    data: Any
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


class ProviderCallError(LLMError):
    """``retryable``: worth another attempt. ``may_have_billed``: charge the reservation in full."""

    def __init__(self, message: str, *, retryable: bool, may_have_billed: bool = False,
                 usage: ProviderReply | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.may_have_billed = may_have_billed
        self.usage = usage


class ProviderAdapter(Protocol):
    name: ProviderName
    billed: bool

    async def call(self, request: ProviderRequest, credentials: Credentials) -> ProviderReply: ...


def _decode(text: str, usage: ProviderReply) -> Any:
    try:
        return parse_json_text(text)
    except ValueError as exc:
        raise ProviderCallError("reply was not valid JSON", retryable=True, usage=usage) from exc


class AnthropicAdapter:
    name: ProviderName = "anthropic"
    billed = True

    async def call(self, request: ProviderRequest, credentials: Credentials) -> ProviderReply:
        if not credentials.api_key:
            raise ProviderCallError("no API key for the Anthropic provider", retryable=False)
        # gzip only: some installed brotli/zstd decoders are incompatible with the SDK's HTTP client.
        client = anthropic.AsyncAnthropic(api_key=credentials.api_key, base_url=credentials.base_url or None,
                                          max_retries=0, timeout=request.timeout_seconds,
                                          default_headers={"Accept-Encoding": "gzip, deflate"})
        try:
            response = await client.messages.create(
                model=request.model,
                max_tokens=request.max_output_tokens,
                # The stage prompt is the stable prefix: cache it; per-call data follows in messages.
                system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": role, "content": text} for role, text in request.turns],
                output_config={"format": {"type": "json_schema", "schema": request.json_schema}},
            )
        except anthropic.APITimeoutError as exc:
            raise ProviderCallError("Anthropic request timed out", retryable=True, may_have_billed=True) from exc
        except anthropic.APIConnectionError as exc:
            reason = type(exc.__cause__ or exc).__name__
            raise ProviderCallError(f"could not reach Anthropic ({reason})", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderCallError("Anthropic rate limit", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code in (408, 409, 429) or exc.status_code >= 500
            raise ProviderCallError(f"Anthropic error {exc.status_code}", retryable=retryable) from exc
        finally:
            await client.close()
        u = response.usage
        usage = ProviderReply(data=None, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                              cache_write_tokens=getattr(u, "cache_creation_input_tokens", None) or 0,
                              cache_read_tokens=getattr(u, "cache_read_input_tokens", None) or 0)
        if response.stop_reason == "refusal":
            raise ProviderCallError("the model declined the request", retryable=False, usage=usage)
        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderReply(data=_decode(text, usage), input_tokens=usage.input_tokens,
                             output_tokens=usage.output_tokens, cache_write_tokens=usage.cache_write_tokens,
                             cache_read_tokens=usage.cache_read_tokens)


class OpenAICompatibleAdapter:
    name: ProviderName = "openai_compatible"
    billed = True

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def call(self, request: ProviderRequest, credentials: Credentials) -> ProviderReply:
        if not credentials.base_url:
            raise ProviderCallError("no base URL for the OpenAI-compatible provider", retryable=False)
        mode = credentials.options.get("json_mode", "json_schema")
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "messages": [{"role": "system", "content": request.system}]
            + [{"role": role, "content": text} for role, text in request.turns],
        }
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "result", "strict": True, "schema": request.json_schema}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {credentials.api_key}"} if credentials.api_key else {}
        url = credentials.base_url.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds, transport=self._transport) as http:
                resp = await http.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderCallError("provider request timed out", retryable=True, may_have_billed=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderCallError("could not reach the provider", retryable=True) from exc
        if resp.status_code >= 400:
            retryable = resp.status_code in (408, 409, 429) or resp.status_code >= 500
            raise ProviderCallError(f"provider error {resp.status_code}", retryable=retryable)
        payload = resp.json()
        u = payload.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        usage = ProviderReply(data=None, input_tokens=max(int(u.get("prompt_tokens", 0)) - cached, 0),
                              output_tokens=int(u.get("completion_tokens", 0)), cache_read_tokens=cached)
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderCallError("provider returned no choices", retryable=True, usage=usage)
        text = (choices[0].get("message") or {}).get("content") or ""
        return ProviderReply(data=_decode(text, usage), input_tokens=usage.input_tokens,
                             output_tokens=usage.output_tokens, cache_read_tokens=usage.cache_read_tokens)


class ClaudeCliAdapter:
    """The owner's Claude subscription via ``claude -p``. Opt-in, PC only, not billed."""

    name: ProviderName = "claude_cli"
    billed = False

    def __init__(self, executable: str = "claude") -> None:
        self._executable = executable

    def command(self, request: ProviderRequest) -> list[str]:
        return [self._executable, "-p", "--output-format", "json", "--json-schema", json.dumps(request.json_schema),
                "--model", request.model, "--system-prompt", request.system, "--tools", "",
                "--no-session-persistence", "--strict-mcp-config"]

    async def call(self, request: ProviderRequest, credentials: Credentials) -> ProviderReply:
        exe = shutil.which(self._executable)
        if exe is None:
            raise ProviderCallError("the claude CLI is not installed on this machine", retryable=False)
        prompt = "\n\n".join(text for _, text in request.turns)
        cmd = self.command(request)
        cmd[0] = exe
        proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _err = await asyncio.wait_for(proc.communicate(prompt.encode()), request.timeout_seconds)
        except TimeoutError as exc:
            proc.kill()
            raise ProviderCallError("claude CLI timed out", retryable=True, may_have_billed=True) from exc
        if proc.returncode != 0:
            raise ProviderCallError(f"claude CLI exited with {proc.returncode}", retryable=True)
        try:
            payload = json.loads(out.decode())
        except ValueError as exc:
            raise ProviderCallError("claude CLI printed no JSON", retryable=True) from exc
        u = payload.get("usage") or {}
        usage = ProviderReply(data=None, input_tokens=int(u.get("input_tokens", 0)),
                              output_tokens=int(u.get("output_tokens", 0)),
                              cache_write_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
                              cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0))
        if payload.get("is_error"):
            raise ProviderCallError("claude CLI reported an error", retryable=True, usage=usage)
        data = payload.get("structured_output")
        if data is None:
            data = _decode(str(payload.get("result", "")), usage)
        return ProviderReply(data=data, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                             cache_write_tokens=usage.cache_write_tokens, cache_read_tokens=usage.cache_read_tokens)


def default_adapters() -> dict[str, ProviderAdapter]:
    return {"anthropic": AnthropicAdapter(), "openai_compatible": OpenAICompatibleAdapter(),
            "claude_cli": ClaudeCliAdapter()}
