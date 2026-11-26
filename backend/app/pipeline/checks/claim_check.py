"""The model claim check (DESIGN.md 9 step 3): a second pass that looks only for unsupported claims.

It runs after the code checks and can only ADD findings: its reply is never used to clear, soften or
replace a code finding. The draft text is model output that may echo a job posting, so it goes to the
model as a data block, not as instructions. A budget refusal or a failed call is reported as a warning
that the model check did not run; the code checks still decide.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import BudgetExhausted, LLMClient, LLMError, Message, TextPart
from app.llm.prompts import active_prompt
from app.llm.untrusted import data_block
from app.pipeline.checks.findings import Finding, Status
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import FactView

CHECK = "claim_check"
STAGE = "claim_check"


class ClaimFlag(BaseModel):
    path: str = Field(description="The item's path exactly as given, e.g. experience[0].bullets[1]")
    problem: str
    fact_ids: list[str] = Field(default_factory=list)


class ClaimCheckOut(BaseModel):
    flags: list[ClaimFlag] = Field(default_factory=list)


def build_messages(prompt: str, items: Sequence[Item], cited: Mapping[str, Sequence[FactView]]) -> list[Message]:
    lines = [f"{it.path} | cites: {', '.join(it.fact_ids) or 'none'} | {it.text}" for it in items]
    facts = {f.code: f for fs in cited.values() for f in fs}
    fact_lines = "\n".join(f"{c}: {f.text}" for c, f in sorted(facts.items())) or "(no cited facts)"
    return [
        Message(role="system", parts=[TextPart(prompt)]),
        Message(role="user", parts=[
            TextPart(f"The cited facts (approved by the owner):\n{fact_lines}"),
            TextPart("The generated sentences follow, one per line as 'path | cites | text'. Report flags by path."),
            data_block("\n".join(lines), "draft sentences"),
        ]),
    ]


async def run(session: AsyncSession, client: LLMClient, items: Sequence[Item],
              cited: Mapping[str, Sequence[FactView]], *, severity: Status, model: str | None = None,
              ) -> tuple[list[Finding], int]:
    """Findings from the model pass and its cost in micros."""
    if not items:
        return [], 0
    prompt = await active_prompt(session, STAGE)
    messages = build_messages(prompt.text if prompt else "", items, cited)
    paths = {it.path for it in items}
    try:
        limit = await client.estimate_cost_micros(STAGE, messages, model=model, schema=ClaimCheckOut)
        out, usage = await client.complete(STAGE, messages, ClaimCheckOut, max_cost_micros=limit, model=model)
    except BudgetExhausted as exc:
        return [Finding(CHECK, "warn", f"model claim check did not run: budget ({exc.scope})")], 0
    except LLMError as exc:
        return [Finding(CHECK, "warn", f"model claim check did not run: {str(exc)[:200]}")], 0
    findings = [Finding(CHECK, severity, f.problem.strip()[:500] or "unsupported claim",
                        f.path if f.path in paths else None) for f in out.flags]
    return findings, usage.cost_micros
