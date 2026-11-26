"""Turn ``Message`` lists into provider-neutral text, enforcing two invariants on the way:

- every ``DataBlock`` is wrapped by ``wrap_untrusted`` and the data preamble joins the system text;
- nothing that looks like a credential reaches a prompt (``SecretInPrompt``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.llm.client import DataBlock, LLMError, Message, TextPart
from app.llm.untrusted import UNTRUSTED_PREAMBLE, wrap_untrusted

# Credential shapes that must never be sent to a model (API keys, bearer tokens, private keys,
# runner tokens, card-like numbers). Kept narrow so ordinary job text does not trip it.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-(?:ant-|or-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bnch_[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
)


class SecretInPrompt(LLMError):
    """A message matched a credential pattern; the call is refused before anything is sent."""


def assert_no_secrets(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretInPrompt("refused: a message looks like it contains a credential")


@dataclass
class RenderedPrompt:
    system: str
    turns: list[tuple[Literal["user", "assistant"], str]] = field(default_factory=list)
    has_untrusted: bool = False

    @property
    def all_text(self) -> str:
        return self.system + "\n".join(t for _, t in self.turns)


def render(messages: Sequence[Message]) -> RenderedPrompt:
    system_parts: list[str] = []
    turns: list[tuple[Literal["user", "assistant"], str]] = []
    has_untrusted = False
    for message in messages:
        chunks: list[str] = []
        for part in message.parts:
            if isinstance(part, DataBlock):
                if message.role == "system":
                    raise LLMError("untrusted data may not be placed in a system message")
                chunks.append(wrap_untrusted(part.content, part.label).block)
                has_untrusted = True
            elif isinstance(part, TextPart):
                chunks.append(part.text)
        text = "\n\n".join(chunks)
        if message.role == "system":
            system_parts.append(text)
        elif turns and turns[-1][0] == message.role:
            turns[-1] = (message.role, turns[-1][1] + "\n\n" + text)
        else:
            turns.append((message.role, text))
    if has_untrusted:
        system_parts.append(UNTRUSTED_PREAMBLE)
    if not turns or turns[0][0] != "user":
        turns.insert(0, ("user", "Follow the instructions above."))
    prompt = RenderedPrompt(system="\n\n".join(system_parts), turns=turns, has_untrusted=has_untrusted)
    assert_no_secrets(prompt.all_text)
    return prompt


def _strict(node: Any) -> Any:
    """JSON Schema tightened for structured output: closed objects, every property required."""
    if isinstance(node, dict):
        out = {k: _strict(v) for k, v in node.items() if k not in ("title", "default")}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def json_schema_for(schema: type[BaseModel]) -> dict[str, Any]:
    return _strict(schema.model_json_schema())


def schema_instruction(schema: type[BaseModel]) -> str:
    return ("Reply with one JSON object only, no prose and no code fences, matching this JSON Schema:\n"
            + json.dumps(json_schema_for(schema), sort_keys=True))


def parse_json_text(text: str) -> Any:
    """Parse a model's JSON reply, tolerating a code fence around it."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        stripped = stripped.rsplit("```", 1)[0]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(stripped[start:end + 1])
