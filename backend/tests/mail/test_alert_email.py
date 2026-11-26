"""Alert-email source: cards from invented alert mails become RawJobs; links stay data."""

# ruff: noqa: E501  (invented fixtures and long assertions)
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.sources import registry as _registry  # noqa: F401  (registers connectors)
from app.sources.alert_email import AlertEmailConnector, MailAccess, cards_from_text, clean_url, jobs_from_message
from app.sources.base import SearchContext, SourceError, connector_class, registered_connectors
from tests.mail.helpers import NOW, FakeMailbox, inbound
from tests.sources.support import FakeFetcher

pytestmark = pytest.mark.nodb

HTML = """
<html><body>
<p>3 new jobs for "data analyst" in Lusaka</p>
<table>
 <tr><td><a href="https://www.board.example.com/comm/jobs/view/4001?trk=email&utm_source=a&refId=zz">Data Analyst</a></td></tr>
 <tr><td>Acme Ltd &middot; Lusaka, Zambia</td></tr>
 <tr><td><a href="https://www.board.example.com/comm/jobs/view/4001?trk=email&utm_source=a&refId=zz">View job</a></td></tr>
 <tr><td><a href="https://www.board.example.com/comm/jobs/view/4002?trk=x">Reporting Officer</a></td></tr>
 <tr><td>Beta Foods</td></tr><tr><td>Ndola</td></tr>
 <tr><td><a href="https://www.board.example.com/jobs/">See more jobs</a></td></tr>
 <tr><td><a href="https://www.board.example.com/unsubscribe?id=1">Unsubscribe</a></td></tr>
</table>
<script>var x = "https://www.board.example.com/jobs/view/999"</script>
</body></html>
"""

TEXT = """New jobs for you

Finance Analyst
Gamma Bank - Kitwe
https://www.board.example.com/viewjob?jk=abc123&utm_medium=email

Field Engineer
https://www.board.example.com/viewjob?jk=def456

Manage alerts: https://www.board.example.com/alerts
"""


def test_html_cards_become_jobs_with_clean_links():
    jobs = jobs_from_message(inbound(sender="alerts@board.example.com", html=HTML, body=""))
    assert [j.title for j in jobs] == ["Data Analyst", "Reporting Officer"]
    first, second = jobs
    assert first.employer == "Acme Ltd" and first.location_raw == "Lusaka, Zambia"
    assert first.source_url == "https://www.board.example.com/comm/jobs/view/4001" and first.apply_url == first.source_url
    assert second.employer == "Beta Foods" and second.location_raw == "Ndola"
    assert second.source_url.endswith("/4002")
    assert first.extra["link_is_tracking"] and first.extra["alert_sender"] == "alerts@board.example.com"
    assert first.pay_text is None and first.deadline is None  # unknown stays unknown


def test_text_cards_fall_back_when_there_is_no_html():
    jobs = jobs_from_message(inbound(sender="alerts@board.example.com", body=TEXT))
    assert [(j.title, j.employer, j.location_raw) for j in jobs] == [
        ("Finance Analyst", "Gamma Bank", "Kitwe"), ("Field Engineer", "Unknown employer", None)]
    assert jobs[0].source_url == "https://www.board.example.com/viewjob?jk=abc123"
    assert cards_from_text("no links here") == []


def test_clean_url_drops_tracking_but_keeps_ids():
    assert clean_url("https://x.example.com/viewjob?jk=1&utm_campaign=z&trk=q&lang=en") == \
        "https://x.example.com/viewjob?jk=1&lang=en"


def connector(box: FakeMailbox, limit: int = 200):
    async def resolver(connection_id):
        return MailAccess(box, 14, limit)

    return AlertEmailConnector(FakeFetcher(), resolver)


def ctx(**config):
    return SearchContext("c", [], [], [], {"connection_id": str(uuid.uuid4()), "senders": ["alerts@board.example.com"],
                                           **config})


async def test_search_keeps_only_configured_senders_and_dedupes():
    box = FakeMailbox()
    box.inbox = [
        inbound(sender="alerts@board.example.com", html=HTML, body="", received=NOW),
        inbound(sender="alerts@board.example.com", html=HTML, body="", received=NOW - timedelta(days=1),
                message_id="older"),
        inbound(sender="spam@evil.example.net", html=HTML.replace("4001", "6666"), body=""),
    ]
    jobs = await connector(box).search(ctx(), None)
    assert [j.title for j in jobs] == ["Data Analyst", "Reporting Officer"]
    assert all("6666" not in j.source_url for j in jobs)


async def test_search_respects_since_and_domain_senders():
    box = FakeMailbox()
    box.inbox = [inbound(sender="jobs@mail.board.example.com", html=HTML, body="", received=NOW)]
    conn = connector(box)
    assert len(await conn.search(ctx(senders=["board.example.com"]), None)) == 2
    assert await conn.search(ctx(senders=["board.example.com"]), NOW + timedelta(days=1)) == []


async def test_a_failing_mailbox_is_a_source_error():
    from app.connect.mailbox import MailError

    class Down(FakeMailbox):
        async def list_messages(self, since, *, limit=200):
            raise MailError("down")

    with pytest.raises(SourceError):
        await connector(Down()).search(ctx(), None)


def test_config_is_validated_and_the_connector_is_registered():
    c = connector(FakeMailbox())
    assert "alert_email" in registered_connectors() and connector_class("alert_email") is AlertEmailConnector
    assert c.access == "email" and c.permitted_actions == frozenset({"search"})
    with pytest.raises(ValueError):
        c.validate_config({"senders": ["a@b.example.com"]})
    with pytest.raises(ValueError):
        c.validate_config({"connection_id": str(uuid.uuid4()), "senders": []})
    ok = c.validate_config({"connection_id": str(uuid.uuid4()), "senders": " Alerts@Board.Example.com "})
    assert ok["senders"] == ["alerts@board.example.com"]


async def test_check_open_is_unknown():
    assert await connector(FakeMailbox()).check_open("https://www.board.example.com/viewjob?jk=1") == "unknown"
