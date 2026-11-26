"""History CSV import: parse, preview diff, commit, repeatable, transactional, marked imported."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.kit.importers import history
from app.models.applications import Application, ApplicationEvent, Stage
from app.models.search import Job, JobSighting
from tests.tracking.helpers import make_app, make_job

CSV = Path(__file__).parent / "fixtures" / "history.csv"


def _upload(path_or_bytes: Path | bytes, name: str = "history.csv"):
    data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    return {"file": (name, data, "text/csv")}


async def _counts(session) -> tuple[int, int, int, int]:
    n = [await session.scalar(select(func.count()).select_from(t))
         for t in (Job, JobSighting, Application, ApplicationEvent)]
    return tuple(n)  # type: ignore[return-value]


@pytest.mark.nodb
def test_parse_maps_statuses_and_keeps_every_column() -> None:
    parsed = history.parse_csv(CSV.read_bytes())
    assert parsed.errors == [] and len(parsed.rows) == 6
    by_id = {r.id: r for r in parsed.rows}
    assert by_id["H001"].stage == Stage.submitted and by_id["H001"].fit == 4
    assert by_id["H001"].notes == 'Referred by a friend; "strong fit"'
    assert by_id["H004"].stage == Stage.ready  # tailored
    assert by_id["H006"].stage == Stage.skipped and by_id["H003"].stage == Stage.shortlisted
    assert by_id["H002"].next_step_due.isoformat() == "2026-10-02"
    assert by_id["H005"].link is None


@pytest.mark.nodb
def test_parse_reports_bad_rows_without_stopping() -> None:
    text = ("id,company,role,status,fit_1to5,date_applied\n"
            "1,A Co,Analyst,applied,3,2026-09-01\n"
            "2,B Co,Analyst,hired,3,\n"
            "3,C Co,Analyst,applied,9,\n"
            "4,D Co,Analyst,applied,3,31/02/2026\n"
            "1,E Co,Analyst,applied,,\n"
            ",F Co,Analyst,applied,,\n")
    parsed = history.parse_csv(text)
    assert [r.id for r in parsed.rows] == ["1"]
    messages = {e.line: e.message for e in parsed.errors}
    assert "'hired'" in messages[3] and "between 1 and 5" in messages[4] and "date_applied" in messages[5]
    assert "more than once" in messages[6] and "id is empty" in messages[7]


@pytest.mark.nodb
def test_parse_accepts_zambian_day_first_dates_and_rejects_missing_columns() -> None:
    parsed = history.parse_csv("id,company,role,status,date_applied\n1,A,B,applied,05/09/2026\n")
    assert parsed.rows[0].date_applied.isoformat() == "2026-09-05"
    with pytest.raises(history.HistoryFormatError, match="missing columns: status"):
        history.parse_csv("id,company,role\n1,A,B\n")
    with pytest.raises(history.HistoryFormatError):
        history.parse_csv("")


async def test_preview_is_a_diff_and_writes_nothing(owner_client, session) -> None:
    before = await _counts(session)
    r = await owner_client.post("/api/applications/import/preview", files=_upload(CSV))
    assert r.status_code == 200
    body = r.json()
    assert (body["create"], body["update"], body["unchanged"], body["skip"]) == (6, 0, 0, 0)
    assert body["errors"] == [] and len(body["content_hash"]) == 64
    h1 = next(row for row in body["rows"] if row["key"] == "history:H001")
    assert h1["action"] == "create" and h1["job"] == "new" and h1["stage"] == "submitted"
    changed = {c["field"]: c["after"] for c in h1["changes"]}
    assert changed["stage"] == "submitted" and changed["applied_at"] == "2026-09-05"
    assert changed["next_step"] == "Chase the recruiter" and changed["legacy_fit"] == 4
    assert changed["owner_attested"] is True
    assert await _counts(session) == before


async def test_confirm_imports_everything_marked_imported(owner_client, session) -> None:
    preview = (await owner_client.post("/api/applications/import/preview", files=_upload(CSV))).json()
    r = await owner_client.post("/api/applications/import/confirm", files=_upload(CSV),
                                data={"content_hash": preview["content_hash"]})
    assert r.status_code == 200
    assert (r.json()["created"], r.json()["updated"], r.json()["errors"]) == (6, 0, 0)
    assert await session.scalar(select(func.count()).select_from(Job)) == 6
    assert await session.scalar(select(func.count()).select_from(JobSighting)) == 5  # H005 has no link
    assert set(await session.scalars(select(Job.origin))) == {"import"}
    apps = {a.import_key: a for a in await session.scalars(select(Application))}
    assert set(apps) == {f"history:H00{i}" for i in range(1, 7)}
    assert {a.origin for a in apps.values()} == {"import"}
    h1 = apps["history:H001"]
    assert (h1.stage, h1.legacy_fit, h1.notes, h1.next_step) == (
        Stage.submitted, 4, 'Referred by a friend; "strong fit"', "Chase the recruiter")
    assert h1.applied_at.date().isoformat() == "2026-09-05" and h1.owner_attested and h1.applied_outside
    assert h1.confirmation_evidence == [] and h1.submitted_snapshot is None  # no invented evidence
    assert h1.import_meta["track"] == "data" and h1.import_meta["source"] == "Example Board"
    assert apps["history:H003"].owner_attested is False and apps["history:H003"].applied_at is None
    assert apps["history:H005"].stage == Stage.rejected and apps["history:H005"].ended_at is not None
    assert apps["history:H006"].stage == Stage.skipped
    events = await session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == h1.id))
    assert [(e.kind, e.actor) for e in events] == [("imported", "import")]
    job = await session.get(Job, h1.job_id)
    assert (job.title, job.employer, job.deadline.isoformat(), job.apply_url) == (
        "Data Analyst", "Zambezi Analytics Ltd", "2026-09-30", "https://jobs.example.com/zambezi/101")
    assert job.location.raw == "Lusaka, Zambia"


async def test_importing_twice_yields_no_duplicates(owner_client, session) -> None:
    async def run():
        preview = (await owner_client.post("/api/applications/import/preview", files=_upload(CSV))).json()
        done = await owner_client.post("/api/applications/import/confirm", files=_upload(CSV),
                                       data={"content_hash": preview["content_hash"]})
        return preview, done.json()

    await run()
    after_first = await _counts(session)
    preview, result = await run()
    assert (preview["create"], preview["update"], preview["unchanged"]) == (0, 0, 6)
    assert (result["created"], result["updated"], result["unchanged"]) == (0, 0, 6)
    assert await _counts(session) == after_first


async def test_reimport_updates_only_what_changed_with_a_field_level_diff(owner_client, session) -> None:
    await owner_client.post("/api/applications/import/confirm", files=_upload(CSV), data={
        "content_hash": history.parse_csv(CSV.read_bytes()).content_hash})
    text = CSV.read_text(encoding="utf-8")
    text = text.replace("H003,Luangwa Foods,Operations Lead,\"Ndola, Zambia\",ops,5,https://jobs.example.com/luangwa/9,"
                        "Direct,2026-09-10,,shortlisted,,,,Tailor the CV,,2026-09-10,",
                        "H003,Luangwa Foods,Operations Lead,\"Ndola, Zambia\",ops,5,https://jobs.example.com/luangwa/9,"
                        "Direct,2026-09-10,,applied,2026-09-11,2026-09-12,owner,Wait for reply,2026-09-26,2026-09-12,"
                        "Applied online")
    assert "Wait for reply" in text
    preview = (await owner_client.post("/api/applications/import/preview", files=_upload(text.encode()))).json()
    assert (preview["create"], preview["update"], preview["unchanged"]) == (0, 1, 5)
    row = next(r for r in preview["rows"] if r["action"] == "update")
    changes = {c["field"]: (c["before"], c["after"]) for c in row["changes"]}
    assert changes["stage"] == ("shortlisted", "submitted")
    assert changes["next_step"] == ("Tailor the CV", "Wait for reply")
    assert changes["notes"] == (None, "Applied online")
    assert changes["applied_at"] == (None, "2026-09-12")
    await owner_client.post("/api/applications/import/confirm", files=_upload(text.encode()),
                            data={"content_hash": preview["content_hash"]})
    app = await session.scalar(select(Application).where(Application.import_key == "history:H003"))
    assert app.stage == Stage.submitted and app.notes == "Applied online" and app.owner_attested
    events = list(await session.scalars(select(ApplicationEvent.kind).where(ApplicationEvent.application_id == app.id)
                                        .order_by(ApplicationEvent.created_at)))
    assert events == ["imported", "import_update"]
    assert await session.scalar(select(func.count()).select_from(Application)) == 6


async def test_confirm_must_match_the_previewed_file(owner_client) -> None:
    r = await owner_client.post("/api/applications/import/confirm", files=_upload(CSV),
                                data={"content_hash": "0" * 64})
    assert r.status_code == 409


async def test_bad_rows_are_reported_and_skipped_and_a_bad_file_is_refused(owner_client, session) -> None:
    text = (b"id,company,role,status\nA1,Alpha Co,Clerk,applied\nA2,Beta Co,Clerk,hired\n")
    preview = (await owner_client.post("/api/applications/import/preview", files=_upload(text))).json()
    assert preview["create"] == 1 and preview["errors"][0]["line"] == 3
    done = await owner_client.post("/api/applications/import/confirm", files=_upload(text),
                                   data={"content_hash": preview["content_hash"]})
    assert done.json()["created"] == 1 and done.json()["errors"] == 1
    bad = await owner_client.post("/api/applications/import/preview", files=_upload(b"id,company\n1,A\n"))
    assert bad.status_code == 422


async def test_import_reuses_a_known_job_and_leaves_an_already_tracked_one_alone(owner_client, session) -> None:
    known = await make_job(session, "Data Analyst", "Zambezi Analytics Ltd", url="https://jobs.example.com/zambezi/101")
    tracked = await make_job(session, "Site Engineer", "Kafue Works")
    mine = await make_app(session, tracked, Stage.ready)
    await session.commit()
    preview = (await owner_client.post("/api/applications/import/preview", files=_upload(CSV))).json()
    rows = {r["key"]: r for r in preview["rows"]}
    assert rows["history:H001"]["job"] == "existing"
    assert rows["history:H002"]["action"] == "skip" and rows["history:H002"]["application_id"] == str(mine.id)
    await owner_client.post("/api/applications/import/confirm", files=_upload(CSV),
                            data={"content_hash": preview["content_hash"]})
    imported = await session.scalar(select(Application).where(Application.import_key == "history:H001"))
    assert imported.job_id == known.id
    assert (await session.get(Application, mine.id)).stage == Stage.ready
    assert await session.scalar(select(func.count()).select_from(Job)) == 6  # 4 new + 2 known


async def test_commit_is_transactional(session) -> None:
    parsed = history.parse_csv(CSV.read_bytes())
    parsed.rows[-1].stage = "not-a-stage"  # type: ignore[assignment]  # forces a failure part-way through
    with pytest.raises(Exception):
        await history.commit(session, parsed, actor="owner")
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(Application)) == 0
    assert await session.scalar(select(func.count()).select_from(Job)) == 0
