"""The two kit exports (CONTRACTS 7, DESIGN.md 5.5 and 18.5).

``snapshot`` reads the database into a ``KitFile`` plus the vault file bytes. ``share_setup`` is
that snapshot with every personal section emptied and the personal parts of what remains
removed (pay floors, seniority, lead facts, guardrails that name terms); ``personal_backup`` is
everything. ``build_zip`` writes the same bytes for the same kit: sorted entries, a fixed
timestamp, sorted vault listing. Secrets (provider keys, tokens, connection credentials) are not
Kit data and are never read here.
"""

from __future__ import annotations

import enum
import hashlib
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.clock import utcnow
from app.kit import scan, vault
from app.kit.schema import (
    KIT_SCHEMA_VERSION,
    KitAlias,
    KitAnswer,
    KitCampaign,
    KitCustomFacet,
    KitExperience,
    KitFact,
    KitFile,
    KitGuardrail,
    KitHistoryItem,
    KitPerson,
    KitPrompt,
    KitReference,
    KitRubric,
    KitSavedView,
    KitSkill,
    KitSource,
    KitTagRule,
    KitTemplate,
    KitTheme,
    KitTrack,
    KitVaultDocument,
    KitWatchedEmployer,
)
from app.models.applications import Application
from app.models.base import ReviewState
from app.models.kit import (
    Answer,
    Experience,
    Fact,
    Guardrail,
    Person,
    Prompt,
    Reference,
    Skill,
    Template,
    Track,
    VaultDocument,
)
from app.models.platform import Theme
from app.models.search import (
    Campaign,
    CustomFacet,
    EmployerAlias,
    Job,
    Rubric,
    RubricStatus,
    SavedView,
    SkillAlias,
    Source,
    TagRule,
    WatchedEmployer,
)

ExportKind = Literal["share_setup", "personal_backup"]
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
# Guardrail types whose parameters carry no personal terms; the rest name the owner's own words.
SHAREABLE_GUARDRAILS = frozenset({"format", "limit", "attach_policy"})
PERSONAL_SECTIONS = ("person", "experiences", "facts", "skills", "references", "answers", "vault", "history")


@dataclass
class KitBundle:
    kit: KitFile
    vault_files: dict[str, bytes] = field(default_factory=dict)
    confirmed: set[tuple[str, str]] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    known_personal: list[tuple[str, str]] = field(default_factory=list)


def plain(v: Any) -> Any:
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, list | tuple):
        return [plain(x) for x in v]
    return v


def _cols(row: Any, names: tuple[str, ...], **over: Any) -> dict[str, Any]:
    out = {n: plain(getattr(row, n)) for n in names}
    out.update(over)
    return out


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:limit].strip("-")
    return s or "x"


def json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def experience_refs(experiences: list[Experience]) -> dict[uuid.UUID, str]:
    """Stable, unique refs derived from the experience itself (never from a database id)."""
    refs: dict[uuid.UUID, str] = {}
    used: set[str] = set()
    for e in sorted(experiences, key=lambda x: (x.org.casefold(), x.start_date or "", x.end_date or "")):
        base = _slug(f"{e.org}-{(e.start_date or '')[:7]}", 55)
        ref, n = base, 2
        while ref in used:
            ref, n = f"{base}-{n}", n + 1
        used.add(ref)
        refs[e.id] = ref
    return refs


def _vault_ext(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else ""


async def snapshot(session: AsyncSession, *, exported_at: datetime | None = None,
                   files_dir: Path | None = None) -> KitBundle:
    """Everything the database holds for the Kit and setup, as a ``personal_backup`` ``KitFile``."""
    from app.core.config import get_config

    files_dir = files_dir or get_config().files_dir
    warnings: list[str] = []
    confirmed: set[tuple[str, str]] = set()
    known: list[tuple[str, str]] = []

    def mark(entity: str, key: str, row: Any) -> None:
        if getattr(row, "review_state", None) == ReviewState.confirmed:
            confirmed.add((entity, key))

    person: KitPerson | None = None
    row = (await session.scalars(select(Person).limit(1))).first()
    if row is not None:
        person = KitPerson.model_validate(_cols(
            row, ("full_name", "preferred_name", "email", "phone", "location", "home_country", "timezone", "links",
                  "extra_fields")))
        mark("person", "person", row)
        for fld in ("full_name", "preferred_name", "email", "phone", "location"):
            f = getattr(row, fld)
            if f is not None:
                known.append(("name" if "name" in fld else fld, f.value))
        known.extend(("url", f.value) for f in row.links.values())
        known.extend(("id_number", f.value) for f in row.extra_fields.values())

    exps = list((await session.scalars(select(Experience))).all())
    refs = experience_refs(exps)
    experiences = []
    for e in exps:
        experiences.append(KitExperience.model_validate(_cols(
            e, ("org", "titles", "location", "start_date", "end_date", "title_variants", "forbidden_titles"),
            ref=refs[e.id])))
        mark("experience", f"{e.org}|{e.start_date}", e)

    facts = []
    for f in (await session.scalars(select(Fact))).all():
        facts.append(KitFact.model_validate(_cols(
            f, ("code", "kind", "text", "canonical_wording", "tags", "tracks", "status", "keep_out_of_prompts",
                "confidence_note"), experience_ref=refs.get(f.experience_id) if f.experience_id else None)))
        mark("fact", f.code, f)

    skills = []
    for s in (await session.scalars(select(Skill))).all():
        skills.append(KitSkill.model_validate(_cols(s, ("name", "group", "level", "claim", "note"))))
        mark("skill", s.name, s)

    references = []
    for r in (await session.scalars(select(Reference))).all():
        references.append(KitReference.model_validate(_cols(
            r, ("name", "role", "organisation", "contact_email", "contact_phone", "consent", "share_policy"))))
        mark("reference", f"{r.name}|{r.organisation}", r)
        known.extend(("name", v) for v in (r.name,))
        known.extend((k, v) for k, v in (("email", r.contact_email), ("phone", r.contact_phone)) if v)

    track_rows = list((await session.scalars(select(Track))).all())
    tracks = []
    for t in track_rows:
        tracks.append(KitTrack.model_validate(_cols(
            t, ("key", "name", "priority", "example_titles", "lead_fact_codes", "summary_fact_code", "tone_notes"))))
        mark("track", t.key, t)

    guardrails = []
    for g in (await session.scalars(select(Guardrail))).all():
        guardrails.append(KitGuardrail.model_validate(_cols(
            g, ("name", "scope", "severity", "strictness", "params", "reason"))))
        mark("guardrail", g.name, g)

    answers = []
    for a in (await session.scalars(select(Answer))).all():
        ka = KitAnswer.model_validate(_cols(
            a, ("patterns", "value", "value_type", "conditions", "answer_class", "material", "scope", "scope_ref",
                "forced_choice", "review_after")))
        answers.append(ka)
        mark("answer", answer_key(ka), a)

    vault_docs: list[KitVaultDocument] = []
    vault_files: dict[str, bytes] = {}
    for d in (await session.scalars(select(VaultDocument))).all():
        try:
            content = vault.resolve(files_dir, d.file_path).read_bytes()
        except (OSError, ValueError):
            warnings.append(f"vault file missing, left out of the export: {d.title}")
            continue
        sha = vault.sha256_hex(content)
        if sha != d.sha256:
            warnings.append(f"vault file changed on disk since it was stored, left out: {d.title}")
            continue
        path = f"vault/{sha}{_vault_ext(d.file_path)}"
        vault_docs.append(KitVaultDocument(path=path, title=d.title, doc_type=d.doc_type,  # type: ignore[arg-type]
                                           sha256=sha, sensitivity=d.sensitivity.value))  # type: ignore[arg-type]
        vault_files[path] = content
        mark("vault", sha, d)

    templates = []
    for t in (await session.scalars(select(Template).where(Template.builtin.is_(False)))).all():
        templates.append(KitTemplate.model_validate(_cols(
            t, ("key", "kind", "name", "html", "css", "section_order", "limits", "accent"))))
        mark("template", t.key, t)

    prompts = [KitPrompt(stage=p.stage, text=p.text, version=p.version) for p in await _exported_prompts(session)]

    rubric_rows = await _exported_rubrics(session)
    rubrics = [KitRubric(name=r.name, body=r.body) for r in rubric_rows]
    rubric_names = {r.id: r.name for r in (await session.scalars(select(Rubric))).all()}

    source_rows = list((await session.scalars(select(Source))).all())
    sources = [KitSource.model_validate(_cols(
        s, ("connector", "name", "access", "config", "access_notes", "rate_limit", "permitted_actions")))
        for s in source_rows]
    source_names = {s.id: s.name for s in source_rows}
    track_keys = {t.id: t.key for t in track_rows}

    campaigns = []
    for c in (await session.scalars(select(Campaign))).all():
        campaigns.append(KitCampaign.model_validate(_cols(
            c, ("name", "priority", "criteria", "unknown_data_policy", "automation"),
            track_key=track_keys.get(c.track_id) if c.track_id else None,
            rubric_name=rubric_names.get(c.rubric_id) if c.rubric_id else None,
            source_names=sorted(source_names[i] for i in c.source_ids if i in source_names))))
        mark("campaign", c.name, c)

    watched = [KitWatchedEmployer.model_validate(_cols(
        w, ("name", "board_type", "board_slug", "priority", "cooldown_days", "always_ask_first")))
        for w in (await session.scalars(select(WatchedEmployer))).all()]
    employer_aliases = [KitAlias(alias=a.alias, canonical=a.canonical)
                        for a in (await session.scalars(select(EmployerAlias))).all()]
    skill_aliases = [KitAlias(alias=a.alias, canonical=a.canonical)
                     for a in (await session.scalars(select(SkillAlias))).all()]
    tag_rules = [KitTagRule(tag=t.tag, conditions=t.conditions) for t in (await session.scalars(select(TagRule))).all()]
    facets = [KitCustomFacet(key=f.key, question=f.question)
              for f in (await session.scalars(select(CustomFacet))).all()]
    views = [KitSavedView(name=v.name, body=v.body, pinned=v.pinned)
             for v in (await session.scalars(select(SavedView))).all()]
    themes = [KitTheme.model_validate({
        "name": t.name, "description": t.description, "fonts": t.fonts.model_dump(), "radius": t.radius,
        "density": t.density, "light": t.light, "dark": t.dark, "chart": t.chart, "score": t.score.model_dump()})
        for t in (await session.scalars(select(Theme).where(Theme.builtin.is_(False)))).all()]

    history = await _history(session)

    kit = KitFile(
        schema_version=KIT_SCHEMA_VERSION, kind="personal_backup", exported_at=exported_at or utcnow(),
        app_version=__version__, person=person,
        experiences=sorted(experiences, key=lambda x: (x.org.casefold(), x.start_date or "", x.ref)),
        facts=sorted(facts, key=lambda f: int(f.code[2:])),
        skills=sorted(skills, key=lambda s: s.name.casefold()),
        references=sorted(references, key=lambda r: (r.name.casefold(), r.organisation or "")),
        tracks=sorted(tracks, key=lambda t: t.key),
        guardrails=sorted(guardrails, key=lambda g: g.name.casefold()),
        answers=sorted(answers, key=answer_key),
        vault=sorted(vault_docs, key=lambda v: v.sha256),
        templates=sorted(templates, key=lambda t: t.key),
        prompts=sorted(prompts, key=lambda p: (p.stage, p.version)),
        rubrics=sorted(rubrics, key=lambda r: r.name.casefold()),
        campaigns=sorted(campaigns, key=lambda c: c.name.casefold()),
        sources=sorted(sources, key=lambda s: (s.connector, s.name.casefold())),
        watched_employers=sorted(watched, key=lambda w: (w.board_type, w.board_slug)),
        employer_aliases=sorted(employer_aliases, key=lambda a: a.alias.casefold()),
        skill_aliases=sorted(skill_aliases, key=lambda a: a.alias.casefold()),
        tag_rules=sorted(tag_rules, key=lambda t: (t.tag, json_key(t.conditions.model_dump(mode="json")))),
        custom_facets=sorted(facets, key=lambda f: f.key),
        saved_views=sorted(views, key=lambda v: v.name.casefold()),
        themes=sorted(themes, key=lambda t: t.name.casefold()),
        history=history,
    )
    return KitBundle(kit=kit, vault_files=vault_files, confirmed=confirmed, warnings=warnings, known_personal=known)


def answer_key(a: KitAnswer) -> str:
    cond = json_key(a.conditions.model_dump(mode="json"))
    return f"{a.patterns.canonical}|{a.scope}|{a.scope_ref or ''}|{hashlib.sha1(cond.encode()).hexdigest()[:8]}"  # noqa: S324


async def _exported_prompts(session: AsyncSession) -> list[Prompt]:
    best: dict[str, Prompt] = {}
    for p in (await session.scalars(select(Prompt))).all():
        cur = best.get(p.stage)
        if cur is None or (p.active, p.version) > (cur.active, cur.version):
            best[p.stage] = p
    return list(best.values())


async def _exported_rubrics(session: AsyncSession) -> list[Rubric]:
    best: dict[str, Rubric] = {}
    for r in (await session.scalars(select(Rubric).where(Rubric.status != RubricStatus.retired))).all():
        cur = best.get(r.name)
        if cur is None or r.version > cur.version:
            best[r.name] = r
    return list(best.values())


async def _history(session: AsyncSession) -> list[KitHistoryItem]:
    rows = (await session.execute(
        select(Application, Job).join(Job, Job.id == Application.job_id)
        .where(Application.applied_at.is_not(None)))).all()
    items = []
    for app, job in rows:
        assert app.applied_at is not None
        items.append(KitHistoryItem(
            employer=job.employer, title=job.title, applied_on=app.applied_at.astimezone(UTC).date(),
            url=job.apply_url, requisition_id=job.requisition_id, stage=app.stage.value,
            channel=app.channel.value if app.channel else "manual"))
    return sorted(items, key=lambda h: (h.applied_on, h.employer.casefold(), h.title.casefold()))


# ----- the two kinds -------------------------------------------------------------------------


def to_share_setup(bundle: KitBundle) -> KitBundle:
    """Personal sections emptied, personal parts of the rest removed. Never mutates ``bundle``."""
    kit = bundle.kit
    campaigns = [c.model_copy(update={
        "criteria": c.criteria.model_copy(update={"pay_floors": [], "seniority": []})}) for c in kit.campaigns]
    tracks = [t.model_copy(update={"lead_fact_codes": [], "summary_fact_code": None}) for t in kit.tracks]
    guardrails = [g for g in kit.guardrails if g.params.type in SHAREABLE_GUARDRAILS]
    shared = kit.model_copy(update={
        "kind": "share_setup", "person": None, "experiences": [], "facts": [], "skills": [], "references": [],
        "answers": [], "vault": [], "history": [], "campaigns": campaigns, "tracks": tracks,
        "guardrails": guardrails})
    shared = KitFile.model_validate(shared.model_dump(mode="json"))  # the personal-sections rule is enforced here
    return KitBundle(kit=shared, vault_files={}, confirmed=set(), warnings=list(bundle.warnings),
                     known_personal=bundle.known_personal)


def counts(kit: KitFile) -> dict[str, int]:
    return {name: len(getattr(kit, name)) for name in KitFile.model_fields
            if isinstance(getattr(kit, name), list) and getattr(kit, name)} | ({"person": 1} if kit.person else {})


def personal_details(bundle: KitBundle) -> list[scan.Hit]:
    return scan.scan(bundle.kit.model_dump(mode="json"), bundle.known_personal)


async def prepare(session: AsyncSession, kind: ExportKind, *, exported_at: datetime | None = None,
                  files_dir: Path | None = None) -> KitBundle:
    full = await snapshot(session, exported_at=exported_at, files_dir=files_dir)
    return full if kind == "personal_backup" else to_share_setup(full)


# ----- the file ------------------------------------------------------------------------------


def kit_json_bytes(kit: KitFile) -> bytes:
    return (json.dumps(kit.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_zip(bundle: KitBundle) -> bytes:
    """``kit.json`` plus ``vault/<sha256><ext>`` files. Same bundle, same bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, content in [("kit.json", kit_json_bytes(bundle.kit)), *sorted(bundle.vault_files.items())]:
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    return buf.getvalue()


def file_name(kind: ExportKind, at: datetime) -> str:
    label = "backup" if kind == "personal_backup" else "setup"
    return f"nchito-{label}-{at.strftime('%Y%m%d')}.kit.zip"


# ----- prepared downloads --------------------------------------------------------------------


@dataclass(frozen=True)
class StoredExport:
    export_id: str
    path: Path
    file_name: str
    sha256: str
    expires_at: datetime


def _exports_dir(files_dir: Path) -> Path:
    return files_dir / "exports"


def store_export(files_dir: Path, data: bytes, name: str, *, lifetime_minutes: int,
                 now: datetime | None = None) -> StoredExport:
    now = now or utcnow()
    purge_expired(files_dir, now)
    export_id = uuid.uuid4().hex
    folder = _exports_dir(files_dir) / export_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    expires = now + timedelta(minutes=lifetime_minutes)
    sha = hashlib.sha256(data).hexdigest()
    (folder / "meta.json").write_text(json.dumps({"file_name": name, "sha256": sha, "expires_at": expires.isoformat()}))
    return StoredExport(export_id, folder / name, name, sha, expires)


def find_export(files_dir: Path, export_id: str, now: datetime | None = None) -> StoredExport | None:
    if not re.fullmatch(r"[0-9a-f]{32}", export_id):
        return None
    folder = _exports_dir(files_dir) / export_id
    try:
        meta = json.loads((folder / "meta.json").read_text())
        expires = datetime.fromisoformat(meta["expires_at"])
        path = folder / Path(meta["file_name"]).name
    except (OSError, ValueError, KeyError):
        return None
    if expires <= (now or utcnow()) or not path.is_file():
        return None
    return StoredExport(export_id, path, path.name, meta["sha256"], expires)


def purge_expired(files_dir: Path, now: datetime | None = None) -> None:
    root = _exports_dir(files_dir)
    if not root.is_dir():
        return
    now = now or utcnow()
    for folder in root.iterdir():
        if folder.is_dir() and find_export(files_dir, folder.name, now) is None:
            for f in folder.iterdir():
                f.unlink(missing_ok=True)
            folder.rmdir()
