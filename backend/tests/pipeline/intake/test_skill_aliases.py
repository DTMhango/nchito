"""Skill alias CRUD re-canonicalises stored job skills from the extraction cache, with no fetch or model call."""

from __future__ import annotations

from sqlalchemy import select

from app.models.search import Job
from app.pipeline import orchestrator
from tests.pipeline.intake.fakes import raw
from tests.pipeline.intake.test_orchestrator import setup

EXTRACT = {"required_skills": ["PowerBI", "Python"], "preferred_skills": ["power bi"],
           "requirements": [{"text": "Experience with PowerBI", "kind": "required", "skill": "PowerBI"}]}


async def test_alias_changes_recanonicalise_without_refetching(owner_client, session, rig):
    _, _, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1")])
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    assert job.facets.required_skills == ["PowerBI", "Python"]
    await session.commit()
    llm_calls, fetches = len(rig.llm.calls), len(conn.checked)

    made = await owner_client.post("/api/skill-aliases", json={"alias": "PowerBI", "canonical": "Power BI"})
    assert made.status_code == 201, made.text
    await session.refresh(job)
    assert job.facets.required_skills == ["Power BI", "Python"] and job.facets.preferred_skills == ["Power BI"]
    assert job.requirements[0].skill == "Power BI"

    alias_id = made.json()["id"]
    changed = await owner_client.put(f"/api/skill-aliases/{alias_id}", json={"alias": "PowerBI", "canonical": "PBI"})
    assert changed.status_code == 200
    await session.refresh(job)
    assert job.facets.required_skills == ["PBI", "Python"]  # from the cached raw names, not the earlier canonical

    assert (await owner_client.delete(f"/api/skill-aliases/{alias_id}")).status_code == 204
    await session.refresh(job)
    assert job.facets.required_skills == ["PowerBI", "Python"]
    assert len(rig.llm.calls) == llm_calls and len(conn.checked) == fetches  # nothing re-fetched or re-asked
