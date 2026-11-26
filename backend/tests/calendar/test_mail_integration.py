"""An interview invitation in the mailbox becomes a proposed event, through the real sync and the real parser."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.connect import mail_sync
from app.connect.mail_common import MAX_CALENDAR_PART_BYTES, message_id_for, parse_rfc822
from app.models.applications import PendingAction, Stage
from app.models.calendar import InterviewEvent
from app.models.platform import Connection, ConnectionProvider
from tests.calendar.helpers import ics_invite
from tests.mail.helpers import ME, NOW, FakeMailbox, make_setup

CONFIG = {"from_address": ME, "imap_host": "imap.example.com", "smtp_host": "smtp.example.com", "read_folder": "Jobs"}


def raw_with_calendar(ref: str, *, ics: bytes | None, body: str = "We would like to invite you to an interview.",
                      filename: str | None = None, content_type: tuple[str, str] = ("text", "calendar")) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "hr@acme.example.com", ME, "Interview invitation"
    m["Date"] = "Thu, 26 Nov 2026 10:00:00 +0000"
    m["Message-ID"] = "<invite-1@mail.example.com>"
    m["In-Reply-To"] = ref
    m["References"] = ref
    m.set_content(body)
    if ics is not None:
        m.add_attachment(ics, maintype=content_type[0], subtype=content_type[1], filename=filename)
    return m.as_bytes()


def test_parser_keeps_calendar_parts_and_drops_oversized_ones() -> None:
    msg = parse_rfc822(raw_with_calendar("<x@y>", ics=ics_invite(), filename="invite.ics"))
    assert len(msg.calendars) == 1 and b"BEGIN:VEVENT" in msg.calendars[0]
    by_name = parse_rfc822(raw_with_calendar("<x@y>", ics=ics_invite(), filename="invite.ics", content_type=("application", "octet-stream")))
    assert len(by_name.calendars) == 1
    huge = parse_rfc822(raw_with_calendar("<x@y>", ics=b"BEGIN:VCALENDAR" + b"x" * (MAX_CALENDAR_PART_BYTES + 10), filename="a.ics"))
    assert huge.calendars == ()
    plain = parse_rfc822(raw_with_calendar("<x@y>", ics=None))
    assert plain.calendars == ()


async def test_invitation_with_ics_is_synced_into_a_proposal_and_the_stage_is_only_proposed(session) -> None:
    setup = await make_setup(session, stage=Stage.submitted, applied=True)
    conn = Connection(provider=ConnectionProvider.imap_smtp, label="Test", config=CONFIG, scopes_granted=[], health="unknown", enabled=True)
    session.add(conn)
    await session.commit()
    ref = message_id_for(str(setup.attempt.id), ME)
    msg = parse_rfc822(raw_with_calendar(ref, ics=ics_invite(), filename="invite.ics"))
    box = FakeMailbox()
    box.inbox = [msg]
    await mail_sync.sync_connection(session, conn, box, None, now=NOW + timedelta(hours=1))
    await session.commit()
    [event] = (await session.scalars(select(InterviewEvent))).all()
    assert event.application_id == setup.app.id and event.status == "proposed" and event.source == "mail"
    assert event.starts_at == datetime(2026, 12, 3, 12, 30, tzinfo=UTC)
    await session.refresh(setup.app)
    assert setup.app.stage == Stage.submitted  # nothing moved on its own
    kinds = sorted(a.detail["kind"] for a in await session.scalars(select(PendingAction)))
    assert kinds == ["interview_event_proposal", "mail_stage_proposal"]
    # a second sync of the same mail adds nothing
    await mail_sync.sync_connection(session, conn, box, None, now=NOW + timedelta(hours=2))
    await session.commit()
    assert len((await session.scalars(select(InterviewEvent))).all()) == 1


async def test_a_failure_while_proposing_never_breaks_the_mail_check(session, monkeypatch) -> None:
    from app.pipeline import events

    async def boom(*a, **k):
        raise RuntimeError("calendar exploded")

    monkeypatch.setattr(events, "propose_from_message", boom)
    setup = await make_setup(session, stage=Stage.submitted, applied=True)
    conn = Connection(provider=ConnectionProvider.imap_smtp, label="Test", config=CONFIG, scopes_granted=[], health="unknown", enabled=True)
    session.add(conn)
    await session.commit()
    msg = parse_rfc822(raw_with_calendar(message_id_for(str(setup.attempt.id), ME), ics=ics_invite()))
    box = FakeMailbox()
    box.inbox = [msg]
    result = await mail_sync.sync_connection(session, conn, box, None, now=NOW + timedelta(hours=1))
    await session.commit()
    assert result.fetched == 1 and result.proposed == 1  # the stage proposal still happened
    assert (await session.scalars(select(InterviewEvent))).all() == []
