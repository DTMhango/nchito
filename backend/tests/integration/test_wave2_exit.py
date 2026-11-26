"""Wave 2 exit test: kit import to a sent email, with fakes only (DESIGN.md 18.6).

The example kit is imported through the data API and confirmed; a real (non-dry) sweep in an approval mode
scores the recorded postings (``FakeLLMClient`` behind the real ledger); the employer's winner is tailored,
checked, rendered and packed; the owner approves; dispatch sends one email through the real email channel to a
fake mailbox, with the packet's attachments; evidence, the stage and the audit chain are recorded. Then: a second
dispatch sends nothing, a timeout is settled from sent items, and an interview reply becomes a proposal that moves
the stage once approved. No network, no paid API.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.apply import dispatch, packets, reconcile
from app.apply.channels import registry
from app.apply.channels.email import EmailChannel, attachment_loader
from app.connect import mail_sync
from app.connect.local_store import LocalFileStore
from app.connect.mail_common import message_id_for
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.llm.fake import FakeCall
from app.models.applications import (
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
    TailoringRequest,
)
from app.models.base import ReviewState
from app.models.documents import ApplicationDocument
from app.models.kit import Answer, Experience, Fact, Person, Skill, Track
from app.models.platform import AuditEvent, Connection, ConnectionProvider
from app.models.search import Campaign, CampaignStatus, Job, Rubric, RubricStatus, Run, RunKind, Source
from app.pipeline import advance, wiring
from app.pipeline.tailoring import service as tailoring
from app.schemas.json_types import AutomationPolicy
from app.worker.queue import run_pipeline
from tests.integration.test_wave1_exit import (
    BOARD_URL,
    FEED_URL,
    FIXTURES,
    LedgeredFake,
    extract_reply,
    make_fake,
    score_reply,
)
from tests.kit.test_kit_io import example_zip
from tests.mail.helpers import FakeMailbox, inbound
from tests.sources.support import FakeFetcher

ME = "mutale.example@example.com"
APPLY_TO = "careers@exampleco.example.com"


def tailor_reply(exp: dict[str, str]) -> dict[str, Any]:
    return {
        "headline": {"text": "Senior data analyst: forecasting and reporting automation", "fact_ids": ["F-1"]},
        "summary": {"text": "Data analyst with eight years in insurance and consumer analytics.", "fact_ids": ["F-1"]},
        "competencies": [{"text": "Forecasting", "fact_ids": ["F-3"]}],
        "experience": [
            {"experience_id": exp["Kafue"], "bullets": [
                {"text": "Cut monthly reporting time from 5 days to 1 day by automating 40 reports in Python and "
                         "Power BI.", "fact_ids": ["F-2"]},
                {"text": "Built a demand forecasting model used by 3 regional teams to plan stock.",
                 "fact_ids": ["F-3"]}]},
            {"experience_id": exp["Zambezi"], "bullets": [
                {"text": "Maintained SQL pipelines feeding the quarterly reserving review.", "fact_ids": ["F-4"]}]},
        ],
        "skills": ["SQL", "Python"],
        "letter": [{"text": "I am applying for the Senior Data Analyst role.", "fact_ids": []},
                   {"text": "I cut monthly reporting time from 5 days to 1 day by automating 40 reports.",
                    "fact_ids": ["F-2"]}],
        "requirement_match": [{"requirement": "SQL", "strength": "strong", "evidence_fact_ids": ["F-4"]}],
        "screening_questions": [],
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "files_dir", tmp_path / "files")
    store = LocalFileStore(tmp_path / "files")
    box = FakeMailbox(from_address=ME)
    fake = make_fake()
    exp: dict[str, str] = {}

    def route(call: FakeCall) -> dict[str, Any]:
        if call.stage == "extract":
            return extract_reply(call)
        if call.stage == "tailor":
            return tailor_reply(exp)
        if call.stage == "claim_check":
            return {"findings": []}
        return score_reply(call)

    fake.default = route
    fetcher = FakeFetcher({BOARD_URL: (200, (FIXTURES / "exampleco_board.json").read_text(encoding="utf-8")),
                           FEED_URL: (200, (FIXTURES / "remote_feed.xml").read_text(encoding="utf-8"))})
    wiring.install()
    from app.pipeline import orchestrator

    async def llm_factory(session, run=None):
        return LedgeredFake(fake, run.id if run else None)

    orchestrator.configure(llm_factory=llm_factory, transport=fetcher)
    queued: list[TailoringRequest] = []

    async def collect(request: TailoringRequest) -> None:
        queued.append(request)

    wiring.set_tailor_enqueuer(collect)

    async def resolver(session, identity):
        return box if identity.lower() == ME else None

    async def channel_factory(session):
        return EmailChannel(attachments=attachment_loader(store), resolver=resolver, hasher=registry.packet_hash)

    registry.register("email", channel_factory, replace=True)

    async def open_check(session, job):
        return None

    dispatch.set_open_checker(open_check)
    yield {"store": store, "box": box, "fake": fake, "exp": exp, "queued": queued}
    dispatch.set_open_checker(None)
    registry.unregister("email")
    wiring.set_tailor_enqueuer(None)
    wiring.uninstall()


async def _import_and_confirm(owner_client, session) -> uuid.UUID:
    r = await owner_client.post("/api/data/import", data={"source": "kit_file"},
                                files={"file": ("example.kit.zip", example_zip(), "application/zip")})
    assert r.status_code == 201, r.text
    commit = await owner_client.post("/api/data/import/commit", json={"import_id": r.json()["import_id"]})
    assert commit.status_code == 200, commit.text
    # Confirm what the import left for review (the owner does this in the onboarding screens).
    for model in (Person, Experience, Fact, Skill, Track, Answer):
        await session.execute(update(model).values(review_state=ReviewState.confirmed))
    await session.execute(update(Source).values(enabled=True))
    await session.execute(update(Rubric).values(status=RubricStatus.active))
    campaign = await session.scalar(select(Campaign))
    rubric = await session.scalar(select(Rubric))
    campaign.rubric_id = rubric.id
    campaign.source_ids = [s.id for s in (await session.scalars(select(Source))).all()]
    campaign.automation = AutomationPolicy(mode="ask_then_apply", per_channel={})
    await session.commit()
    assert (await owner_client.post(f"/api/campaigns/{campaign.id}/confirm")).status_code == 200
    campaign.status = CampaignStatus.active
    session.add(Connection(provider=ConnectionProvider.imap_smtp, label="Mail", enabled=True, health="ok",
                           scopes_granted=[], config={"from_address": ME, "imap_host": "imap.example.com",
                                                      "smtp_host": "smtp.example.com", "read_folder": "Jobs"}))
    # Quiet hours well away from now, so the send-time check lets it through.
    zone = ZoneInfo(await settings_service.get_value(session, "general.timezone"))
    local = datetime.now(UTC).astimezone(zone)
    await settings_service.set_value(session, "automation.quiet_hours_start",
                                     (local + timedelta(hours=6)).strftime("%H:%M"), actor="owner")
    await settings_service.set_value(session, "automation.quiet_hours_end",
                                     (local + timedelta(hours=7)).strftime("%H:%M"), actor="owner")
    await settings_service.set_value(session, "budget.monthly_cap_minor", 500, actor="owner")
    await session.commit()
    return campaign.id


async def _sweep(campaign_id: uuid.UUID) -> Run:
    async with get_sessionmaker()() as s:
        run = Run(kind=RunKind.sweep, campaign_id=campaign_id, dry_run=False, trigger="manual")
        s.add(run)
        await s.commit()
    await run_pipeline.func(run_id=str(run.id))
    async with get_sessionmaker()() as s:
        done = await s.get(Run, run.id)
        assert done is not None
        return done


async def _actions(session, prefix: str = "") -> list[str]:
    return list((await session.scalars(select(AuditEvent.action).where(AuditEvent.action.like(f"{prefix}%"))
                                       .order_by(AuditEvent.created_at))).all())


async def test_kit_import_to_one_sent_email_with_the_full_audit_chain(world, owner_client, session):
    campaign_id = await _import_and_confirm(owner_client, session)
    world["exp"].update({e.org.split()[0]: str(e.id) for e in (await session.scalars(select(Experience))).all()})

    run = await _sweep(campaign_id)
    assert run.status.value == "succeeded", run.error
    session.expire_all()
    senior = await session.scalar(select(Job).where(Job.employer == "ExampleCo (fictional)",
                                                    Job.title == "Senior Data Analyst"))
    assert senior.conflict_state.value == "winner"
    app = await session.scalar(select(Application).where(Application.job_id == senior.id))
    assert app is not None and app.origin == "system" and app.stage == Stage.tailoring
    app_id = app.id
    held = await session.scalar(select(Job).where(Job.title == "Analytics Lead"))
    assert await session.scalar(select(Application).where(Application.job_id == held.id)) is None  # held: not tailored
    request = next(r for r in world["queued"] if r.application_id == app_id)

    senior.apply_email = APPLY_TO  # the posting's application address (invented)
    await session.commit()
    async with get_sessionmaker()() as s:  # what the tailoring task does: draft, check, then render and pack
        status = await tailoring.process(s, LedgeredFake(world["fake"], run.id), request.id)
        await s.commit()
        assert status.value == "done", (await s.get(TailoringRequest, request.id)).error
        prepared = await advance.after_tailored(s, app_id, store=world["store"])
        await s.commit()
    assert prepared is not None and prepared.built, prepared and prepared.reason
    assert prepared.approval_status == "wait_for_owner"

    session.expire_all()
    packet = await packets.current(session, app_id)
    contents = packet.contents
    assert contents.channel == "email" and contents.email.to == [APPLY_TO] and contents.sending_identity == ME
    assert {f.kind for f in contents.files} == {"cv", "letter"}
    for f in contents.files:  # bound to the rendered files of the checked spec, by content hash
        assert hashlib.sha256(await world["store"].get(
            (await session.get(ApplicationDocument, uuid.UUID(f.document_id))).file_key)).hexdigest() == f.sha256
    ask = await session.scalar(select(PendingAction).where(PendingAction.application_id == app_id,
                                                           PendingAction.type == PendingActionType.approve))
    assert ask is not None and ask.status == PendingStatus.open

    r = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": packet.version, "packet_hash": packet.content_hash, "channel": "email"})
    assert r.status_code == 200, r.text

    now = datetime.now(UTC)
    async with get_sessionmaker()() as s:
        queued = await dispatch.queue(s, app_id, now=now)
        assert queued.queued, queued.reason
        await s.commit()
        attempt_id = queued.attempt.id
        later = now + timedelta(minutes=int(await settings_service.get_value(
            s, "automation.email_send_delay_minutes")) + 1)
        assert await dispatch.run(s, attempt_id, now=later) == DispatchStatus.sent
        # A second dispatch attempt for the same packet sends nothing.
        assert await dispatch.run(s, attempt_id, now=later) is None
        again = await dispatch.queue(s, app_id, now=later)
        assert not again.queued
        await s.rollback()

    box = world["box"]
    assert len(box.sent) == 1
    mail = box.sent[0]
    assert list(mail.to) == [APPLY_TO] and mail.idempotency_key == str(attempt_id)
    assert sorted(a.file_name for a in mail.attachments) == sorted(f.name for f in contents.files)
    assert all(hashlib.sha256(a.content).hexdigest() in {f.sha256 for f in contents.files} for a in mail.attachments)

    session.expire_all()
    attempt = await session.get(DispatchAttempt, attempt_id)
    app = await session.get(Application, app_id)
    assert attempt.status == DispatchStatus.sent and attempt.evidence.kind == "sent_mail_id"
    assert app.stage == Stage.submitted and app.confirmation_evidence
    trail = await _actions(session)
    for action in ("application.tailored", "packet.built", "application.approved", "permit.granted",
                   "permit.consumed", "dispatch.reserved", "dispatch.started", "dispatch.sent"):
        assert action in trail, action
    assert trail.index("application.tailored") < trail.index("packet.built") < trail.index(
        "application.approved") < trail.index("permit.consumed") < trail.index("dispatch.sent")
    tailored = await session.scalar(select(AuditEvent).where(AuditEvent.action == "application.tailored"))
    assert set(tailored.detail["facts_sent"]) >= {"F-2"}  # the facts behind the documents

    # An interview reply raises a proposal; approving it moves the stage.
    async with get_sessionmaker()() as s:
        conn = await s.scalar(select(Connection))
        ref = message_id_for(str(attempt_id), ME)
        reply = inbound(sender="talent@exampleco.example.com", subject="Re: Application: Senior Data Analyst",
                        body="We would like to invite you to an interview next week.",
                        headers={"in-reply-to": ref, "references": ref})
        mailbox = FakeMailbox(from_address=ME)
        mailbox.inbox = [reply]
        result = await mail_sync.sync_connection(s, conn, mailbox, None)
        await s.commit()
        assert result.proposed == 1
    proposal = await session.scalar(select(PendingAction).where(
        PendingAction.application_id == app_id, PendingAction.status == PendingStatus.open))
    assert proposal.detail["kind"] == mail_sync.PROPOSAL_KIND and proposal.detail["proposed_stage"] == "interview"
    r = await owner_client.post(f"/api/pending-actions/{proposal.id}/resolve", json={"resolution": "approved"})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert (await session.get(Application, app_id)).stage == Stage.interview


async def test_a_timeout_is_uncertain_and_reconcile_settles_it_from_sent_items(world, owner_client, session):
    from tests.apply.helpers import setup_app, setup_campaign

    world["box"].mode = "timeout"
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer="Timeout Example", now=datetime.now(UTC))
        built = await packets.build(s, app, packets.PacketDraft(
            channel="email", destination_url="", sending_identity=ME,
            email=packets.PacketEmail(to=[APPLY_TO], subject="Application", body="Hello")), actor="owner")
        from app.apply import approval

        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner")
        await settings_service.set_value(s, "automation.quiet_hours_start", "00:00", actor="owner")
        await settings_service.set_value(s, "automation.quiet_hours_end", "00:01", actor="owner")
        await s.commit()
        now = datetime.now(UTC).replace(hour=12)
        queued = await dispatch.queue(s, app.id, now=now)
        assert queued.queued, queued.reason
        await s.commit()
        attempt_id = queued.attempt.id
        assert await dispatch.run(s, attempt_id, now=now + timedelta(hours=1)) == DispatchStatus.unknown
        assert len(world["box"].sent) == 1  # handed over; the answer was lost
        attempt = await s.get(DispatchAttempt, attempt_id)
        settled = await reconcile.check(s, attempt)
        await s.commit()
    assert settled is not None
    session.expire_all()
    assert (await session.get(DispatchAttempt, attempt_id)).status == DispatchStatus.sent
    assert len(world["box"].sent) == 1  # reconciled from sent items, never resent


async def test_a_packet_with_generated_documents_needs_the_checked_spec(session):
    from tests.apply.helpers import setup_app, setup_campaign

    campaign = await setup_campaign(session)
    _, app = await setup_app(session, campaign, employer="Gate Example", now=datetime.now(UTC))
    cv = packets.PacketFile(name="cv.pdf", kind="cv", sha256="a" * 64, document_id=str(uuid.uuid4()))
    draft = packets.PacketDraft(channel="email", destination_url="", sending_identity=ME, files=[cv],
                                email=packets.PacketEmail(to=[APPLY_TO], subject="Application", body="Hello"))
    with pytest.raises(packets.PacketError) as err:
        await packets.build(session, app, draft, actor="owner")
    assert err.value.status == 409 and "no tailored spec" in err.value.message
