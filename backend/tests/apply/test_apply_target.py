"""The role's application address (app.apply.target): found in the posting, unconfirmed until the owner
confirms it or its domain is trusted; only a usable address is sent to (invented data only)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.apply import approval, packets, target
from app.core.db import get_sessionmaker
from app.models.platform import AuditEvent
from app.models.search import Job, TrustedSite
from tests.apply.helpers import email_draft, setup_app, setup_campaign

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
POSTED = "careers@beta.example.com"


async def _job(mode: str = "ask_then_apply", **per_channel: str):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s, mode=mode, **per_channel)
        job, app = await setup_app(s, campaign, employer="Beta Example", now=NOW)
        job.apply_email, job.apply_email_confirmed = POSTED, None
        job.raw_text = f"Data Analyst at Beta Example.\nTo apply, email your CV to {POSTED} by Friday."
        await s.commit()
        return job.id, app.id


def test_evidence_quote_is_the_sentence_that_gives_the_address():
    text = "We are hiring. Send your CV and letter to jobs@acme.example.com. Thank you."
    assert target.evidence_quote(text, "JOBS@acme.example.com") == "Send your CV and letter to jobs@acme.example.com."
    assert target.evidence_quote(text, "other@example.com") is None


async def test_job_detail_shows_an_unconfirmed_posting_address_and_why_email_is_not_available(owner_client):
    job_id, _ = await _job()
    detail = (await owner_client.get(f"/api/jobs/{job_id}")).json()
    email = detail["apply_email"]
    assert email["address"] == POSTED and email["found_in"] == "posting_text"
    assert email["evidence"] == f"To apply, email your CV to {POSTED} by Friday."
    assert not email["confirmed"] and not email["usable"] and not email["trusted_domain"]
    by = {c["channel"]: c for c in detail["apply_channel_candidates"]}
    assert not by["email"]["available"] and "not confirmed" in by["email"]["reason"]
    assert by["manual"]["available"]


async def test_owner_confirms_then_corrects_the_address(owner_client, session):
    job_id, _ = await _job()
    r = await owner_client.put(f"/api/jobs/{job_id}/apply-email", json={"confirmed": True})
    assert r.status_code == 200, r.text
    email = r.json()["apply_email"]
    assert email["confirmed"] and email["usable"] and email["confirmed_by"] == "owner"
    # A corrected address is the owner's; confirming it is a separate, explicit choice.
    r = await owner_client.put(f"/api/jobs/{job_id}/apply-email",
                               json={"address": "hiring@beta.example.com", "confirmed": False})
    email = r.json()["apply_email"]
    assert email["address"] == "hiring@beta.example.com" and email["found_in"] == "owner"
    assert not email["confirmed"] and not email["usable"]
    # Back to the posting's address: its earlier confirmation does not come back by itself.
    r = await owner_client.put(f"/api/jobs/{job_id}/apply-email", json={"address": None, "confirmed": False})
    assert r.json()["apply_email"]["address"] == POSTED and not r.json()["apply_email"]["confirmed"]
    trail = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "job.apply_email_set")
                                   .order_by(AuditEvent.created_at))).all()
    assert [e.detail["after"] for e in trail] == [POSTED, "hiring@beta.example.com", POSTED]


async def test_bad_address_and_nothing_to_confirm_carry_codes(owner_client, session):
    job_id, _ = await _job()
    r = await owner_client.put(f"/api/jobs/{job_id}/apply-email", json={"address": "not an address"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_address"
    job = await session.get(Job, job_id)
    job.apply_email = None
    await session.commit()
    r = await owner_client.put(f"/api/jobs/{job_id}/apply-email", json={"confirmed": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_address"


async def test_a_trusted_domain_is_usable_without_confirmation(owner_client, session):
    job_id, _ = await _job()
    session.add(TrustedSite(domain="beta.example.com", trusted_by="owner"))
    await session.commit()
    email = (await owner_client.get(f"/api/jobs/{job_id}")).json()["apply_email"]
    assert email["trusted_domain"] and email["usable"] and not email["confirmed"]


async def test_an_unconfirmed_address_is_never_sent_automatically(session):
    campaign = await setup_campaign(session, mode="ask_then_apply", email="auto_apply")
    job, app = await setup_app(session, campaign, employer="Gamma Example", now=NOW)
    job.apply_email_confirmed = None  # found in the posting, not confirmed
    built = await packets.build(session, app, email_draft(), actor="system", now=NOW)
    out = await approval.after_packet_built(session, app, built.packet, now=NOW)
    assert not out.approved and out.status == "wait_for_owner" and "recipient_confirmed" in out.reason
    # Once the owner confirms the address, the same packet may be approved automatically.
    await target.set_email(session, job, address=None, confirmed=True, actor="owner", now=NOW)
    again = await approval.auto_approve(session, app, built.packet, now=NOW)
    assert again.approved, again.reason


async def test_changing_the_address_retires_a_packet_addressed_elsewhere(session):
    campaign = await setup_campaign(session)
    job, app = await setup_app(session, campaign, employer="Delta Example", now=NOW)
    built = await packets.build(session, app, email_draft(), actor="owner", now=NOW)
    await target.set_email(session, job, address="other@delta.example.com", confirmed=True, actor="owner", now=NOW)
    await session.refresh(built.packet)
    assert built.packet.invalidated_at is not None and "other@delta.example.com" in built.packet.invalidated_reason
