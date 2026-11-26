"""Old-kit importer against a messy folder (all invented): nested folders, mixed file types, a CV as .txt,
.docx and .pdf, criteria as prose or plain lists, salary written many ways, trackers with their own column
names, dates in several formats, duplicate files. Nothing unparsed disappears silently; nothing is confirmed."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from app.core.settings.registry import REGISTRY
from app.kit.importers import history, oldkit, oldkit_tracker
from app.kit.zipsafe import ZipLimits
from tests.conftest import BACKEND
from tests.kit.test_oldkit import make_docx

FIXTURE = BACKEND / "tests" / "fixtures" / "oldkit_messy"
LIMITS = ZipLimits(max_zip_bytes=5_000_000, max_file_bytes=1_000_000, max_files=100)
HEADERS = REGISTRY["data.old_kit_tracker_headers"].default


def messy_zip(extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted(FIXTURE.rglob("*")):
            if path.is_file():
                zf.writestr("my old job hunt/" + path.relative_to(FIXTURE).as_posix(), path.read_bytes())
        for name, content in (extra or {}).items():
            zf.writestr("my old job hunt/" + name, content)
    return buf.getvalue()


def pdf_with(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    y = 800
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 18
    pdf.save()
    return buf.getvalue()


async def build(extra=None, **kw):
    return await oldkit.build(messy_zip(extra), LIMITS, tracker_headers=HEADERS, **kw)


# ----- salary -------------------------------------------------------------------------------------


@pytest.mark.nodb
@pytest.mark.parametrize("text,expected", [
    ("K45,000 pm permanent", ("ZMW", 4_500_000, "month", "permanent")),
    ("$3k/month contract", ("USD", 300_000, "month", "contract")),
    ("ZMW 540k p.a. permanent", ("ZMW", 54_000_000, "year", "permanent")),
    ("45,000 ZMW per month, fixed term", ("ZMW", 4_500_000, "month", "fixed_term")),
    ("£2,000 monthly contract", ("GBP", 200_000, "month", "contract")),
])
def test_salary_in_many_spellings_becomes_a_floor_only_when_everything_is_stated(text, expected):
    floor = oldkit.parse_pay(text)
    assert floor is not None
    assert (floor.currency, floor.amount_minor, floor.period, floor.employment_type) == expected


@pytest.mark.nodb
@pytest.mark.parametrize("text", [
    "K45,000 pm",  # no employment type
    "ZMW 540k permanent",  # no period
    "45,000 per month contract",  # no currency
    "around 30k a month",  # no currency, no type
    "K40,000 - K50,000 pm permanent",  # a range is two amounts
    "K45,000 pm or ZMW 540k p.a. permanent",  # two amounts
    "ZMW 45,000 per month contract or permanent",  # two types
    "ZMW 45,000 monthly, or 500,000 per annum permanent",  # two periods
])
def test_anything_unclear_stays_text(text):
    assert oldkit.parse_pay(text) is None


# ----- dates --------------------------------------------------------------------------------------


@pytest.mark.nodb
def test_dates_are_read_in_several_formats_and_ambiguity_is_flagged():
    assert oldkit_tracker.read_dates("5 Jan 2026") == (date(2026, 1, 5), False)
    assert oldkit_tracker.read_dates("Jan 20 2026") == (date(2026, 1, 20), False)
    assert oldkit_tracker.read_dates("2026/02/03") == (date(2026, 2, 3), False)
    assert oldkit_tracker.read_dates("31/01/2026") == (date(2026, 1, 31), False)
    assert oldkit_tracker.read_dates("03/04/2026") == (date(2026, 4, 3), True)  # day first, flagged
    assert oldkit_tracker.read_dates("46027") == (date(2026, 1, 5), False)  # an Excel serial
    assert oldkit_tracker.read_dates("sometime in march") == (None, False)


@pytest.mark.nodb
def test_job_dates_with_month_names_and_slashes():
    assert oldkit._when("Mar 2020") == ("2020-03", False)
    assert oldkit._when("03/2020") == ("2020-03", False)
    assert oldkit._when("March, 2020") == ("2020-03", False)
    assert oldkit._when("2020") == (None, True)  # a bare year: months are never guessed


# ----- the messy folder ---------------------------------------------------------------------------


async def test_nested_folders_and_a_wrapping_folder_are_read():
    result = await build()
    assert any(c.name.startswith("Criteria from what I want") for c in result.kit.campaigns)
    assert any("Criteria from second criteria" in c.name for c in result.kit.campaigns)


async def test_prose_criteria_are_read_and_the_salary_is_a_floor_only_with_everything_stated():
    result = await build()
    prose = next(c for c in result.kit.campaigns if c.name.startswith("Criteria from what I want")).criteria
    assert prose.titles == ["Reporting Analyst", "Data Analyst", "BI Analyst"]
    assert {(r.place, r.kind) for r in prose.locations} == {("Lusaka", "allow"), ("Ndola", "allow"),
                                                            ("Kenya", "deny")}
    assert prose.work_models == ["remote"]  # "no hybrid" is not "hybrid"
    assert "SQL" in prose.keywords and "Power BI" in prose.keywords
    assert [(p.currency, p.amount_minor, p.period) for p in prose.pay_floors] == [("ZMW", 4_500_000, "month")]
    # the sentence with two amounts and no type was not guessed into a floor: a note for the owner
    assert any("540k" in a.value for a in result.kit.answers) or len(prose.pay_floors) == 1


async def test_plain_bullet_lists_under_bare_headings_are_read_and_unclear_pay_is_kept_as_a_note():
    result = await build()
    lists = next(c for c in result.kit.campaigns if "second criteria" in c.name)
    assert lists.criteria.titles == ["Finance Operations Analyst", "Reconciliation Lead"]
    assert [r.place for r in lists.criteria.locations] == ["Livingstone", "Kitwe"]
    assert lists.criteria.work_models == ["hybrid"]
    assert lists.criteria.pay_floors == []
    notes = [a for a in result.kit.answers if a.patterns.canonical.startswith("Pay floor") and "second criteria" in a.patterns.canonical]  # noqa: E501
    assert len(notes) == 1 and "540k" in notes[0].value and "30k a month" in notes[0].value
    assert all(a.answer_class == "ask_first" for a in notes) and notes[0].review_after == oldkit.today()


async def test_tracker_with_its_own_column_names_dates_and_a_repeated_row():
    result = await build()
    assert result.history_csv is not None
    plan = history.parse_csv(result.history_csv)
    by_company = {r.company: r for r in plan.rows}
    assert len(plan.rows) == 4  # the repeated Zambezi row is left out
    kafue = by_company["Kafue Analytics (Fictional)"]
    assert kafue.status == "applied" and kafue.date_found == date(2026, 1, 5)
    assert kafue.date_applied == date(2026, 1, 7)  # 07/01/2026 read day first
    assert by_company["Luangwa Bank (Fictional)"].status == "interview"
    assert by_company["Luangwa Bank (Fictional)"].closes == date(2026, 1, 31)
    assert by_company["Zambezi Retail Group (Fictional)"].status == "rejected"
    assert by_company["Mulungushi Foods (Fictional)"].date_applied is None  # "sometime in march" is not a date
    assert "Contact person: Mr Example" in (kafue.notes or "")  # an unmapped column is kept, not dropped
    assert any("day first" in n for n in result.notices) and any("could not be read" in n for n in result.notices)
    assert any("repeated row" in n for n in result.notices)


async def test_tracker_without_a_status_column_is_not_imported_and_says_why():
    result = await build()
    assert any(n.startswith("not imported: jobs/Other tracker.csv, no status column was recognised")
               for n in result.notices)


async def test_header_synonyms_are_a_setting_with_a_second_value():
    odd = b"Organisation,Vacancy,Outcome\nExample Co (Fictional),Analyst,applied\n"
    bare = oldkit_tracker.read_tracker(odd.decode(), "x.csv", HEADERS)
    assert bare.why_not is None  # the defaults know these words
    custom = oldkit_tracker.read_tracker("Firma,Posten,Lage\nExample Co,Analyst,applied\n", "x.csv", [])
    assert custom.why_not and "company" in custom.why_not
    mapped = oldkit_tracker.read_tracker("Firma,Posten,Lage\nExample Co,Analyst,applied\n", "x.csv",
                                         ["company: firma", "role: posten", "status: lage"])
    assert mapped.why_not is None and mapped.rows[0]["company"] == "Example Co"


async def test_a_cv_as_text_docx_and_pdf_is_read_and_the_profile_person_is_kept():
    docx = make_docx([("Heading1", "Zed Docx"), ("", "zed.docx@example.com"), ("Heading2", "Work experience"),
                      ("Heading3", "Analyst, Example Docx Co (Fictional), Jan 2019 - Dec 2020"),
                      ("", "Reported things.")])
    pdf = pdf_with(["Pia Pdf", "pia.pdf@example.com", "SKILLS", "Spreadsheet craft"])
    result = await build(extra={"docs/CV Zed.docx": docx, "docs/Resume Pia.pdf": pdf})
    orgs = {e.org for e in result.kit.experiences}
    assert {"Copperline Telecom (Fictional)", "Zambezi Retail Group (Fictional)"} <= orgs
    assert any("Example Docx Co" in o for o in orgs)
    texts = {f.text for f in result.kit.facts}
    assert "Cut month-end reporting from five days to two." in texts
    assert any("Spreadsheet craft" in s.name for s in result.kit.skills)
    starts = {e.org: e.start_date for e in result.kit.experiences}
    assert starts["Copperline Telecom (Fictional)"] == "2020-03"
    assert starts["Zambezi Retail Group (Fictional)"] == "2016-01"
    assert len(result.vault_files) == 2  # the docx and the pdf are also kept as files
    assert result.kit.person is None or result.kit.person.full_name.value == "Chanda Example"


async def test_everything_unparsed_is_listed_by_name_with_the_reason():
    junk = {"misc/photo.gif": b"GIF89a", "misc/tool.exe": b"MZ", "docs/scan.pdf": b"%PDF-1.4 not really",
            "docs/old cv.doc": b"\xd0\xcf\x11\xe0 cv"}
    result = await build(extra=junk)
    listed = [n for n in result.notices if n.startswith("not imported: ")]
    assert any("misc/photo.gif, unsupported file type" in n for n in listed)
    assert any("misc/tool.exe, unsupported file type" in n for n in listed)
    assert any("docs/random thoughts.md, not recognised" in n for n in listed)
    assert any("docs/scan.pdf, kept in the vault; its text is not read" in n for n in listed)
    assert any("docs/old cv.doc" in n and ".doc" in n for n in listed)
    assert any("unconfirmed and may be stale" in n for n in result.notices)


async def test_duplicate_files_are_listed_once_and_read_once():
    once = await build()
    twice = await build(extra={"zz copy/second criteria.txt":
                               (FIXTURE / "notes" / "second criteria.txt").read_bytes()})
    assert any("zz copy/second criteria.txt, identical to notes/second criteria.txt" in n
               for n in twice.notices)
    assert len(twice.kit.campaigns) == len(once.kit.campaigns)


async def test_nothing_from_a_messy_folder_is_confirmed_or_defaulted(session):
    from sqlalchemy import select

    from app.kit.importers import kitfile
    from app.models.base import Origin, ReviewState
    from app.models.kit import Answer, Fact

    result = await build()
    await kitfile.apply(session, kitfile.ParsedKit(kit=result.kit, vault_files=result.vault_files))
    await session.commit()
    facts = list((await session.scalars(select(Fact))).all())
    assert facts and all(f.review_state == ReviewState.needs_review and f.origin == Origin.imported for f in facts)
    assert all("may be stale" in (f.confidence_note or "") for f in facts)
    answers = list((await session.scalars(select(Answer))).all())
    assert answers and all(a.review_state == ReviewState.needs_review for a in answers)
    for track in result.kit.campaigns:  # never inferred: seniority, countries
        assert track.criteria.seniority == []
