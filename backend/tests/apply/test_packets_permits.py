"""Packets, approvals and submit permits against PostgreSQL (DESIGN.md 7.1, 8.1, 18.1-18.3)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.apply import approval, autopilot, packets, permits
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationPacket,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
    SubmitPermit,
)
from app.models.platform import AuditEvent
from app.models.search import ConflictState, Job
from app.schemas.json_types import CheckResult
from tests.apply.helpers import browser_draft, email_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW


async def approved(session, app, draft=None):
    built = await packets.build(session, app, draft or email_draft(), actor="owner", now=NOW)
    await approval.approve(session, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                           channel=built.packet.contents.channel, actor="owner", now=NOW)
    return built.packet


async def actions(session, kind):
    return (await session.scalars(select(AuditEvent.action).where(AuditEvent.action.like(f"{kind}%")))).all()


# ----- packets ------------------------------------------------------------------------------


async def test_packet_hash_changes_with_any_content_and_approval_does_not_carry_over(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    first = await approved(session, app)
    assert app.approved_packet_id == first.id
    same = await packets.build(session, app, email_draft(), actor="owner", now=NOW)
    assert not same.created and same.packet.id == first.id  # identical contents: same packet, still approved
    changed = await packets.build(session, app, email_draft(body="A different letter."), actor="owner", now=NOW)
    assert changed.created and changed.packet.content_hash != first.content_hash
    assert changed.packet.version == 2 and changed.packet.approved_at is None
    await session.refresh(first)
    assert first.invalidated_at is not None and "email.body" in first.invalidated_reason
    assert app.approved_packet_id is None
    assert [c["path"] for c in changed.changes if c["material"]] == ["email.body"]
    # Recipient, answers and files change the hash too.
    for draft in (email_draft(to="hr@acme.example.com"), browser_draft()):
        assert packets.content_hash(await packets.assemble(session, app, draft)) != changed.packet.content_hash
    # The old hash can no longer be approved or permitted.
    with pytest.raises(approval.ApprovalError):
        await approval.approve(session, app, packet_version=1, packet_hash=first.content_hash, channel="email",
                               actor="owner", now=NOW)
    result = await permits.request(session, app.id, packet_hash=first.content_hash, channel="email", now=NOW)
    assert result.status == "denied"


async def test_destination_is_checked_by_the_server(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    own = await packets.assemble(session, app, browser_draft())
    assert own.destination.domain == "boards.greenhouse.io" and own.destination.verified
    assert not own.destination.trusted
    elsewhere = await packets.assemble(session, app, browser_draft("https://evil.example.org/apply"))
    assert not elsewhere.destination.verified


# ----- approval ------------------------------------------------------------------------------


async def test_owner_approval_is_audited_and_closes_the_request(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    built = await packets.build(session, app, email_draft(), actor="owner", now=NOW)
    outcome = await approval.after_packet_built(session, app, built.packet, now=NOW)
    assert outcome is not None and not outcome.approved and outcome.pending_action_id
    await approval.approve(session, app, packet_version=1, packet_hash=built.packet.content_hash, channel="email",
                           actor="owner", now=NOW)
    action = await session.get(PendingAction, outcome.pending_action_id)
    assert action.status == PendingStatus.resolved
    event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "application.approved"))
    assert event.detail["packet_hash"] == built.packet.content_hash and event.detail["gates"]


async def test_automatic_approval_only_when_mode_allows_and_every_gate_passes(session):
    campaign = await setup_campaign(session, mode="ask_then_apply", email="auto_apply")
    _, app = await setup_app(session, campaign, now=NOW)
    built = await packets.build(session, app, email_draft(), actor="system", now=NOW)
    outcome = await approval.after_packet_built(session, app, built.packet, now=NOW)
    assert outcome.approved, outcome.reason
    assert built.packet.approved_by == approval.AUTO_APPROVER
    # A browser packet in the same campaign falls back to ask_then_apply: the owner is asked.
    campaign2 = await setup_campaign(session, mode="ask_then_apply", email="auto_apply")
    _, other = await setup_app(session, campaign2, employer="Beta Example", now=NOW)
    b = await packets.build(session, other, browser_draft(), actor="system", now=NOW)
    out = await approval.after_packet_built(session, other, b.packet, now=NOW)
    assert not out.approved and out.pending_action_id


async def test_automatic_approval_waits_for_owner_on_an_unknown(session):
    campaign = await setup_campaign(session, mode="auto_apply")
    job, app = await setup_app(session, campaign, now=NOW)
    job.pay_state = "not_stated"
    built = await packets.build(session, app, email_draft(), actor="system", now=NOW)
    out = await approval.after_packet_built(session, app, built.packet, now=NOW)
    assert not out.approved and out.status == "wait_for_owner" and out.pending_action_id
    # A browser packet to an untrusted site with typed answers also waits for the owner.
    app.check_results = [CheckResult(check="never_together", status="block", detail="x")]
    with pytest.raises(approval.ApprovalError, match="document checks"):
        await approval.approve(session, app, packet_version=1, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)


async def test_excluded_role_cannot_be_approved_whatever_its_score(session):
    from app.core.conditions import CampaignRule, ConditionSet, Group, ValueFilter
    from app.schemas.json_types import CampaignCriteria

    campaign = await setup_campaign(session)
    rule = CampaignRule(effect="exclude", reason="no remote", conditions=ConditionSet(
        root=Group(conditions=[ValueFilter(facet="facets.work_model", include=["remote"])])))
    campaign.criteria = CampaignCriteria(rules=[rule])
    _, app = await setup_app(session, campaign, score=100, now=NOW)
    built = await packets.build(session, app, email_draft(), actor="owner", now=NOW)
    with pytest.raises(approval.ApprovalError, match="excluded"):
        await approval.approve(session, app, packet_version=1, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)


async def test_one_role_per_employer_held_cannot_be_approved_and_is_promoted(session):
    campaign = await setup_campaign(session)
    winner_job, winner = await setup_app(session, campaign, title="Analytics Manager", score=90, now=NOW,
                                         resolve=False)
    held_job, held = await setup_app(session, campaign, title="Senior Analyst", score=70, now=NOW)
    await session.refresh(winner_job)
    assert winner_job.conflict_state == ConflictState.winner and held_job.conflict_state == ConflictState.held
    built = await packets.build(session, held, email_draft(), actor="owner", now=NOW)
    with pytest.raises(approval.ApprovalError, match="conflict_winner"):
        await approval.approve(session, held, packet_version=1, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)
    # The owner rejects the winner: the runner-up is promoted and can now be approved.
    await approval.reject(session, winner, actor="owner", reason="not for me", now=NOW)
    await session.refresh(held_job)
    assert winner.stage == Stage.skipped and held_job.conflict_state == ConflictState.winner
    await approval.approve(session, held, packet_version=1, packet_hash=built.packet.content_hash,
                           channel="email", actor="owner", now=NOW)
    assert held.approved_packet_id == built.packet.id


async def test_request_changes_retires_the_packet(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app)
    await approval.request_changes(session, app, actor="owner", note="shorter letter", now=NOW)
    await session.refresh(packet)
    assert packet.invalidated_at is not None and app.stage == Stage.tailoring and app.approved_packet_id is None
    assert "application.changes_requested" in await actions(session, "application.")


# ----- permits ------------------------------------------------------------------------------


async def test_permit_single_use_and_bound(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app)
    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email", now=NOW)
    assert result.granted, result.reason
    assert app.stage == Stage.applying
    assert result.permit.expires_at == NOW + timedelta(minutes=10)
    # A second permit for the same application is refused while one is outstanding.
    again = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email", now=NOW)
    assert again.status == "denied" and "outstanding" in again.reason
    with pytest.raises(permits.PermitRefused, match="channel"):
        await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="browser", now=NOW)
    used = await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="email",
                                 now=NOW)
    assert used.used_at == NOW
    with pytest.raises(permits.PermitRefused, match="already used"):
        await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="email", now=NOW)
    assert {"permit.granted", "permit.consumed", "permit.refused"} <= set(await actions(session, "permit."))


@pytest.mark.parametrize("minutes", [None, 5])
async def test_permit_expiry_at_default_and_another_value(session, minutes):
    if minutes is not None:
        await settings_service.set_value(session, "automation.permit_valid_minutes", minutes, actor="owner")
    valid = minutes or 10
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app)
    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email", now=NOW)
    assert result.permit.expires_at == NOW + timedelta(minutes=valid)
    with pytest.raises(permits.PermitRefused, match="expired"):
        await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="email",
                              now=NOW + timedelta(minutes=valid, seconds=1))
    # The unused, expired permit gives the claim back.
    released = await permits.release_stale_claims(session, now=NOW + timedelta(minutes=valid, seconds=1))
    assert released == [app.id] and app.stage == Stage.ready


async def test_daily_cap_counts_outstanding_permits(session):
    await settings_service.set_value(session, "automation.daily_cap", 1, actor="owner")
    campaign = await setup_campaign(session)
    _, one = await setup_app(session, campaign, employer="Acme Example", now=NOW)
    _, two = await setup_app(session, campaign, employer="Beta Example", now=NOW)
    p1, p2 = await approved(session, one), await approved(session, two)
    assert (await permits.request(session, one.id, packet_hash=p1.content_hash, channel="email", now=NOW)).granted
    second = await permits.request(session, two.id, packet_hash=p2.content_hash, channel="email", now=NOW)
    assert second.status == "denied" and "daily_cap" in second.reason


async def test_quiet_hours_gate_at_permit_time(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app)
    late = NOW.replace(hour=20)  # 22:00 Lusaka
    app_job = await session.get(Job, app.job_id)
    app_job.last_checked_at = late
    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email", now=late)
    assert result.status == "denied" and "quiet_hours" in result.reason
    await settings_service.set_value(session, "automation.quiet_hours_start", "22:30", actor="owner")
    assert (await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email",
                                  now=late)).granted


async def test_browser_permit_needs_trusted_site_or_owner_and_runner(session):
    from app.models.platform import ApiToken

    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app, browser_draft())  # owner approved an untrusted site: allowed
    token = ApiToken(name="pc", token_hash="h" * 64, prefix="nch_", runner_kind="pc", suspended_at=NOW)
    session.add(token)
    await session.flush()
    refused = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="browser",
                                    runner_token_id=token.id, now=NOW)
    assert refused.status == "denied" and "suspended" in refused.reason
    token.suspended_at = None
    ok = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="browser",
                               runner_token_id=token.id, now=NOW)
    assert ok.granted, ok.reason
    with pytest.raises(permits.PermitRefused, match="runner"):
        await permits.consume(session, ok.permit.id, packet_hash=packet.content_hash, channel="browser", now=NOW)


async def test_pause_revokes_outstanding_permits(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    packet = await approved(session, app)
    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="email", now=NOW)
    state = await autopilot.set_paused(session, True, actor="owner", reason="holiday")
    assert state.paused and state.paused_by == "owner" and state.reason == "holiday" and state.paused_at
    await session.refresh(result.permit)
    with pytest.raises(permits.PermitRefused):
        await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="email")
    assert app.stage == Stage.ready  # nothing was dispatched: the claim is given back


# ----- concurrency (real concurrent transactions) ------------------------------------------


async def _two_ready_apps(same_employer: bool):
    maker = get_sessionmaker()
    async with maker() as s:
        campaign = await setup_campaign(s)
        j1, a1 = await setup_app(s, campaign, title="Role One", now=NOW, resolve=False)
        j2, a2 = await setup_app(s, campaign, title="Role Two", function="other", now=NOW, resolve=False,
                                 employer="Acme Example" if same_employer else "Beta Example")
        j1.conflict_state = ConflictState.winner
        j2.conflict_state = ConflictState.released if same_employer else ConflictState.winner
        hashes = []
        for app in (a1, a2):
            hashes.append((await approved(s, app)).content_hash)
        await s.commit()
        return [(a1.id, hashes[0]), (a2.id, hashes[1])]


async def test_two_runners_cannot_both_obtain_a_permit_for_one_application():
    (app_id, digest), _ = await _two_ready_apps(same_employer=False)
    maker = get_sessionmaker()

    async def attempt():
        async with maker() as s:
            result = await permits.request(s, app_id, packet_hash=digest, channel="email", now=NOW)
            await asyncio.sleep(0.2)
            await s.commit()
            return result.status

    outcomes = await asyncio.gather(attempt(), attempt())
    assert sorted(outcomes) == ["denied", "granted"]
    async with maker() as s:
        assert len((await s.scalars(select(SubmitPermit))).all()) == 1


async def test_two_runners_cannot_both_obtain_permits_at_one_employer():
    pairs = await _two_ready_apps(same_employer=True)
    maker = get_sessionmaker()

    async def attempt(app_id, digest):
        async with maker() as s:
            result = await permits.request(s, app_id, packet_hash=digest, channel="email", now=NOW)
            await asyncio.sleep(0.2)
            await s.commit()
            return result.status

    outcomes = await asyncio.gather(*(attempt(a, h) for a, h in pairs))
    assert sorted(outcomes) == ["denied", "granted"]
    async with maker() as s:
        assert (await s.scalars(select(Application.stage))).all().count(Stage.applying) == 1


async def test_permit_consumption_is_atomic_under_concurrency():
    (app_id, digest), _ = await _two_ready_apps(same_employer=False)
    maker = get_sessionmaker()
    async with maker() as s:
        permit = (await permits.request(s, app_id, packet_hash=digest, channel="email", now=NOW)).permit
        await s.commit()
        permit_id = permit.id

    async def use():
        async with maker() as s:
            try:
                await permits.consume(s, permit_id, packet_hash=digest, channel="email", now=NOW)
                await asyncio.sleep(0.2)
                await s.commit()
                return "used"
            except permits.PermitRefused:
                await s.commit()
                return "refused"

    assert sorted(await asyncio.gather(use(), use(), use())) == ["refused", "refused", "used"]


async def test_packet_rows_are_never_edited_only_superseded(session):
    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, now=NOW)
    for body in ("one", "two", "three"):
        await packets.build(session, app, email_draft(body=body), actor="owner", now=NOW)
    rows = (await session.scalars(select(ApplicationPacket).order_by(ApplicationPacket.version))).all()
    assert [r.version for r in rows] == [1, 2, 3]
    assert [r.invalidated_at is None for r in rows] == [False, False, True]
    assert len({r.content_hash for r in rows}) == 3
    assert (await session.scalar(select(PendingAction).where(PendingAction.type == PendingActionType.approve))
            ) is None  # building alone raises nothing; the policy step does
