"""The email channel: server-enforced gates, exact packet, no resend, reconcile from sent items."""

from __future__ import annotations

import pytest

from app.apply.channels.base import Channel
from app.apply.channels.email import EmailChannel
from app.core.db import get_sessionmaker
from app.models.applications import DispatchStatus
from tests.mail.helpers import ME, FakeMailbox, file_for, make_packet, make_setup

CV = b"%PDF-1.4 invented cv"


def channel(box: FakeMailbox | None, files: dict[str, bytes] | None = None) -> EmailChannel:
    store = files if files is not None else {"cv.pdf": CV}

    async def load(f):
        return store[f.name]

    async def resolve(session, identity):
        return box

    return EmailChannel(attachments=load, sessionmaker=get_sessionmaker(), resolver=resolve)


async def test_channel_is_a_server_enforced_channel():
    ch = channel(FakeMailbox())
    assert isinstance(ch, Channel) and ch.name == "email" and ch.enforcement == "server"


async def test_sends_exactly_the_packet_and_returns_evidence(session):
    contents = make_packet(files=[file_for(CV)], body="Dear team,\nI apply for REQ-77.")
    setup = await make_setup(session, contents=contents)
    box = FakeMailbox()
    outcome = await channel(box).dispatch(setup.request())
    assert outcome.status == "sent" and outcome.provider_message_id == "gm-1"
    assert outcome.evidence is not None and outcome.evidence.kind == "sent_mail_id" and outcome.evidence.value == "gm-1"
    mail = box.sent[0]
    assert list(mail.to) == ["hr@acme.example.com"] and mail.subject == "Application: Data Analyst"
    assert mail.body_text == "Dear team,\nI apply for REQ-77."
    assert [(a.file_name, a.content) for a in mail.attachments] == [("cv.pdf", CV)]
    assert mail.idempotency_key == str(setup.attempt.id)


async def test_refuses_without_a_permit(session):
    setup = await make_setup(session, with_permit=False)
    box = FakeMailbox()
    outcome = await channel(box).dispatch(setup.request())
    assert outcome.status == "failed" and "permit" in (outcome.error or "") and box.sent == []


async def test_refuses_a_permit_that_was_not_consumed(session):
    setup = await make_setup(session, permit_used=False)
    box = FakeMailbox()
    outcome = await channel(box).dispatch(setup.request())
    assert outcome.status == "failed" and box.sent == []


async def test_refuses_when_the_permit_is_for_another_packet(session):
    setup = await make_setup(session)
    setup.permit.packet_hash = "0" * 64
    await session.commit()
    box = FakeMailbox()
    assert (await channel(box).dispatch(setup.request())).status == "failed" and box.sent == []


async def test_refuses_on_packet_hash_mismatch(session):
    setup = await make_setup(session)
    box = FakeMailbox()
    changed = make_packet(body="A different body than the one approved")
    outcome = await channel(box).dispatch(setup.request(packet=changed))
    assert outcome.status == "failed" and "hash" in (outcome.error or "") and box.sent == []
    outcome = await channel(box).dispatch(setup.request(packet_hash="f" * 64))
    assert outcome.status == "failed" and box.sent == []


async def test_refuses_a_changed_attachment(session):
    setup = await make_setup(session, contents=make_packet(files=[file_for(CV)]))
    box = FakeMailbox()
    outcome = await channel(box, {"cv.pdf": CV + b"edited"}).dispatch(setup.request())
    assert outcome.status == "failed" and "changed" in (outcome.error or "") and box.sent == []


async def test_refuses_a_mailbox_that_is_not_the_sending_identity(session):
    setup = await make_setup(session)
    box = FakeMailbox(from_address="someone.else@example.com")
    assert (await channel(box).dispatch(setup.request())).status == "failed" and box.sent == []
    assert (await channel(None).dispatch(setup.request())).status == "failed"


@pytest.mark.parametrize("status", [DispatchStatus.sent, DispatchStatus.unknown, DispatchStatus.cancelled,
                                    DispatchStatus.failed, DispatchStatus.acknowledged])
async def test_never_sends_an_attempt_that_already_has_an_outcome(session, status):
    setup = await make_setup(session, status=status)
    box = FakeMailbox()
    assert (await channel(box).dispatch(setup.request())).status == "failed" and box.sent == []


async def test_timeout_after_handoff_is_unknown_and_a_second_dispatch_does_not_resend(session):
    setup = await make_setup(session)
    box = FakeMailbox(mode="timeout")  # the provider took the message, the answer never came back
    ch = channel(box)
    first = await ch.dispatch(setup.request())
    assert first.status == "unknown" and first.evidence is None and len(box.sent) == 1
    same_process = await ch.dispatch(setup.request())
    assert same_process.status == "unknown" and len(box.sent) == 1
    restarted = await channel(box).dispatch(setup.request())  # a retried job after a crash must not send again
    assert len(box.sent) == 1
    assert restarted.status == "sent" and restarted.provider_message_id == "gm-1"  # settled from sent items


async def test_reconcile_settles_from_sent_items_and_never_resends(session):
    setup = await make_setup(session, status=DispatchStatus.unknown)
    box = FakeMailbox(mode="timeout")
    ch = channel(box)
    assert (await ch.reconcile(str(setup.attempt.id))).status == "unknown"  # nothing left yet
    assert box.sent == []
    box.sent_ids[str(setup.attempt.id)] = "gm-77"  # it did leave
    outcome = await ch.reconcile(str(setup.attempt.id))
    assert outcome.status == "sent" and outcome.provider_message_id == "gm-77"
    assert outcome.evidence is not None and outcome.evidence.value == "gm-77"
    assert box.sent == []


async def test_a_provider_refusal_is_failed_and_sent_items_are_checked_first(session):
    setup = await make_setup(session)
    box = FakeMailbox(mode="refuse")
    outcome = await channel(box).dispatch(setup.request())
    assert outcome.status == "failed" and outcome.evidence is None


async def test_cancel_only_before_handoff(session):
    setup = await make_setup(session)
    box = FakeMailbox()
    ch = channel(box)
    assert await ch.cancel(str(setup.attempt.id)) is True
    await ch.dispatch(setup.request())
    assert await ch.cancel(str(setup.attempt.id)) is False
    assert await ch.cancel("not-a-uuid") is False


async def test_sending_identity_is_the_connected_address(session):
    setup = await make_setup(session, contents=make_packet(identity=ME.upper()))
    box = FakeMailbox()
    assert (await channel(box).dispatch(setup.request())).status == "sent"
