"""Import a ``*.kit.zip`` (and any proposal built as a ``KitFile``): validate, diff, apply.

``parse_kit_zip`` refuses anything unsafe or unexpected before a byte is trusted: zip-slip names,
oversized members, files outside ``kit.json`` and ``vault/<file>``, a vault file the listing does
not name, a listed file that is missing, and any sha256 that does not match the bytes. A newer
schema version is refused; an older one passes through ``MIGRATIONS`` first.

``plan`` compares the incoming kit with what the database holds and writes nothing. ``apply``
writes in the caller's transaction: Kit rows through ``load_kit`` (every row ``needs_review`` and
``origin=import``), the rest of the setup below. Setup that can act on its own arrives switched
off or at the lowest automation mode: sources disabled, campaigns draft with every criteria group
unconfirmed, rubrics and prompts inactive.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.core.settings.registry import REGISTRY
from app.kit import export
from app.kit.loader import LoadReport, load_kit
from app.kit.schema import KIT_SCHEMA_VERSION, KitFile
from app.kit.zipsafe import UnsafeZip, ZipLimits, read_zip
from app.models.applications import END_STAGES, Application, Channel, Stage
from app.models.base import Origin, ReviewState
from app.models.kit import Prompt, Track
from app.models.platform import Theme
from app.models.search import (
    Campaign,
    CampaignStatus,
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
from app.pipeline import corrections
from app.themes import service as theme_service
from app.themes.schema import ThemeBody

Change = Literal["add", "update", "unchanged", "conflict"]
VAULT_NAME = re.compile(r"^vault/[A-Za-z0-9._-]{1,200}$")
CRITERIA_GROUPS = ("titles", "keywords", "rules", "locations", "work_models", "seniority", "pay_floors",
                   "deprioritise_themes")
REVIEWED_ENTITIES = frozenset({"person", "experience", "fact", "skill", "reference", "track", "guardrail", "answer",
                               "vault_document", "template", "campaign"})
# Section name in KitFile -> entity name used in the diff and in ``exclude_keys``.
ENTITY_OF: dict[str, str] = {
    "person": "person", "experiences": "experience", "facts": "fact", "skills": "skill", "references": "reference",
    "tracks": "track", "guardrails": "guardrail", "answers": "answer", "vault": "vault_document",
    "templates": "template", "prompts": "prompt", "rubrics": "rubric", "campaigns": "campaign",
    "sources": "source", "watched_employers": "watched_employer", "employer_aliases": "employer_alias",
    "skill_aliases": "skill_alias", "tag_rules": "tag_rule", "custom_facets": "custom_facet",
    "saved_views": "saved_view", "themes": "theme", "history": "application_history",
}
# Schema migrations: version N -> N+1, applied in order to the raw JSON. Empty while 1 is current.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class KitImportError(ValueError):
    """The upload cannot be imported; the message is safe to show the owner."""


@dataclass
class ParsedKit:
    kit: KitFile
    vault_files: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class DiffRow:
    entity: str
    key: str
    change: Change
    before: Any = None
    after: Any = None


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise KitImportError("kit.json has no valid schema_version")
    if version > KIT_SCHEMA_VERSION:
        raise KitImportError(f"this kit uses schema version {version}; this app reads up to {KIT_SCHEMA_VERSION}")
    while version < KIT_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise KitImportError(f"no migration from kit schema version {version}")
        raw = step(raw)
        version += 1
        raw["schema_version"] = version
    return raw


def _allowed(name: str) -> bool:
    return name == "kit.json" or bool(VAULT_NAME.fullmatch(name))


def parse_kit_zip(data: bytes, limits: ZipLimits) -> ParsedKit:
    try:
        files, _ = read_zip(data, limits, allow=_allowed)
    except UnsafeZip as exc:
        raise KitImportError(str(exc)) from exc
    if "kit.json" not in files:
        raise KitImportError("the zip has no kit.json")
    try:
        raw = json.loads(files["kit.json"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KitImportError("kit.json is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise KitImportError("kit.json must be a JSON object")
    try:
        kit = KitFile.model_validate(migrate(raw))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise KitImportError(f"kit.json does not match the kit schema ({where}: {first['msg']})") from exc
    vault_files = {n: c for n, c in files.items() if n != "kit.json"}
    listed = {v.path for v in kit.vault}
    if len(listed) != len(kit.vault):
        raise KitImportError("kit.json lists the same vault path twice")
    extra = sorted(set(vault_files) - listed)
    if extra:
        raise KitImportError(f"the zip holds a vault file kit.json does not list: {extra[0]}")
    for doc in kit.vault:
        content = vault_files.get(doc.path)
        if content is None:
            raise KitImportError(f"vault file listed in kit.json is missing from the zip: {doc.path}")
        if hashlib.sha256(content).hexdigest() != doc.sha256:
            raise KitImportError(f"sha256 mismatch for {doc.path}: the file was changed after export")
    return ParsedKit(kit=kit, vault_files=vault_files)


# ----- comparable form -----------------------------------------------------------------------


def _dump(model: Any, **drop: Any) -> dict[str, Any]:
    d = model.model_dump(mode="json")
    for k in drop:
        d.pop(k, None)
    return d


def entity_maps(kit: KitFile) -> dict[str, dict[str, Any]]:
    """``entity -> key -> comparable dict``; keys match what ``export.snapshot`` marks as confirmed."""
    exp_key = {e.ref: f"{e.org}|{e.start_date}" for e in kit.experiences}
    m: dict[str, dict[str, Any]] = {name: {} for name in ENTITY_OF.values()}
    if kit.person:
        m["person"]["person"] = _dump(kit.person)
    for e in kit.experiences:
        m["experience"][exp_key[e.ref]] = _dump(e, ref=None)
    for f in kit.facts:
        d = _dump(f)
        d["experience_ref"] = exp_key.get(f.experience_ref or "")
        m["fact"][f.code] = d
    for s in kit.skills:
        m["skill"][s.name] = _dump(s)
    for r in kit.references:
        m["reference"][f"{r.name}|{r.organisation}"] = _dump(r)
    for t in kit.tracks:
        m["track"][t.key] = _dump(t)
    for g in kit.guardrails:
        m["guardrail"][g.name] = _dump(g)
    for a in kit.answers:
        m["answer"][export.answer_key(a)] = _dump(a)
    for v in kit.vault:
        m["vault_document"][v.sha256] = _dump(v, path=None)
    for t in kit.templates:
        m["template"][t.key] = _dump(t)
    for p in kit.prompts:
        m["prompt"][p.stage] = _dump(p, version=None)
    for r in kit.rubrics:
        m["rubric"][r.name] = _dump(r)
    for c in kit.campaigns:
        m["campaign"][c.name] = _dump(c)
    for s in kit.sources:
        m["source"][f"{s.connector}|{s.name}"] = _dump(s)
    for w in kit.watched_employers:
        m["watched_employer"][f"{w.board_type}|{w.board_slug}"] = _dump(w)
    for a in kit.employer_aliases:
        m["employer_alias"][a.alias] = _dump(a)
    for a in kit.skill_aliases:
        m["skill_alias"][a.alias] = _dump(a)
    for t in kit.tag_rules:
        d = _dump(t)
        m["tag_rule"][tag_rule_key(t.tag, d["conditions"])] = d
    for f in kit.custom_facets:
        m["custom_facet"][f.key] = _dump(f)
    for v in kit.saved_views:
        m["saved_view"][v.name] = _dump(v)
    for t in kit.themes:
        m["theme"][t.name] = _dump(t)
    for h in kit.history:
        m["application_history"][history_key(h.employer, h.title, h.applied_on)] = _dump(h)
    return m


def tag_rule_key(tag: str, conditions: Any) -> str:
    digest = hashlib.sha1(export.json_key(conditions).encode()).hexdigest()  # noqa: S324
    return f"{tag}|{digest[:8]}"


def history_key(employer: str, title: str, applied_on: date) -> str:
    return f"{applied_on.isoformat()}|{' '.join(employer.split()).casefold()}|{' '.join(title.split()).casefold()}"


async def plan(session: AsyncSession, incoming: KitFile, *, files_dir: Any = None) -> list[DiffRow]:
    """What applying ``incoming`` would add, change, or leave alone. Writes nothing."""
    current = await export.snapshot(session, files_dir=files_dir)
    have = entity_maps(current.kit)
    want = entity_maps(incoming)
    rows: list[DiffRow] = []
    for entity in ENTITY_OF.values():
        for key in sorted(want[entity]):
            after = want[entity][key]
            before = have[entity].get(key)
            if before is None:
                rows.append(DiffRow(entity, key, "add", None, after))
            elif before == after:
                rows.append(DiffRow(entity, key, "unchanged"))
            else:
                confirmed = (entity, key) in current.confirmed
                rows.append(DiffRow(entity, key, "conflict" if confirmed else "update", before, after))
    return rows


def diff_key(entity: str, key: str) -> str:
    return f"{entity}:{key}"


def without(kit: KitFile, exclude: set[str]) -> KitFile:
    """``kit`` minus the items named in ``exclude`` (``entity:key``). Dangling references are cleared."""
    if not exclude:
        return kit
    maps = entity_maps(kit)
    drop = {e: {k for k in maps[e] if diff_key(e, k) in exclude} for e in maps}
    exp_key = {e.ref: f"{e.org}|{e.start_date}" for e in kit.experiences}
    keys: dict[str, Callable[[Any], str]] = {
        "experience": lambda x: exp_key[x.ref], "fact": lambda x: x.code, "skill": lambda x: x.name,
        "reference": lambda x: f"{x.name}|{x.organisation}", "track": lambda x: x.key,
        "guardrail": lambda x: x.name, "answer": export.answer_key, "vault_document": lambda x: x.sha256,
        "template": lambda x: x.key, "prompt": lambda x: x.stage, "rubric": lambda x: x.name,
        "campaign": lambda x: x.name, "source": lambda x: f"{x.connector}|{x.name}",
        "watched_employer": lambda x: f"{x.board_type}|{x.board_slug}", "employer_alias": lambda x: x.alias,
        "skill_alias": lambda x: x.alias,
        "tag_rule": lambda x: tag_rule_key(x.tag, x.conditions.model_dump(mode="json")),
        "custom_facet": lambda x: x.key, "saved_view": lambda x: x.name, "theme": lambda x: x.name,
        "application_history": lambda x: history_key(x.employer, x.title, x.applied_on),
    }
    update: dict[str, Any] = {}
    for section, entity in ENTITY_OF.items():
        if entity == "person":
            if drop["person"]:
                update["person"] = None
            continue
        update[section] = [x for x in getattr(kit, section) if keys[entity](x) not in drop[entity]]
    dropped_exps = {e.ref for e in kit.experiences if exp_key[e.ref] in drop["experience"]}
    update["facts"] = [f.model_copy(update={"experience_ref": None}) if f.experience_ref in dropped_exps else f
                       for f in update["facts"]]
    kept_tracks = {t.key for t in update["tracks"]}
    update["campaigns"] = [c.model_copy(update={"track_key": c.track_key if c.track_key in kept_tracks else None})
                           for c in update["campaigns"]]
    return kit.model_copy(update=update)


# ----- apply ---------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    created: int = 0
    updated: int = 0
    needs_review: int = 0
    themes_need_review: list[tuple[str, str]] = field(default_factory=list)  # (api id, name)
    report: LoadReport | None = None
    other: Counter[str] = field(default_factory=Counter)


async def apply(session: AsyncSession, parsed: ParsedKit, *, exclude: set[str] | None = None,
                actor: str = "import") -> ApplyResult:
    """Write the import in the caller's transaction (all of it, or nothing if anything raises)."""
    kit = without(parsed.kit, exclude or set())
    result = ApplyResult()
    report = await load_kit(session, kit, actor=actor, vault_files=parsed.vault_files)
    result.report = report
    created: Counter[str] = Counter(report.created)
    updated: Counter[str] = Counter(report.updated)

    def count(entity: str, outcome: str) -> None:
        if outcome == "created":
            created[entity] += 1
        elif outcome == "updated":
            updated[entity] += 1

    for p in kit.prompts:
        count("prompt", await _prompt(session, p))
    for r in kit.rubrics:
        count("rubric", await _rubric(session, r))
    for s in kit.sources:
        count("source", await _source(session, s))
    for w in kit.watched_employers:
        count("watched_employer", await _watched(session, w))
    for a in kit.employer_aliases:
        count("employer_alias", await _alias(session, EmployerAlias, a.alias, a.canonical))
    for a in kit.skill_aliases:
        count("skill_alias", await _alias(session, SkillAlias, a.alias, a.canonical))
    for t in kit.tag_rules:
        count("tag_rule", await _tag_rule(session, t))
    for f in kit.custom_facets:
        count("custom_facet", await _facet(session, f))
    for v in kit.saved_views:
        count("saved_view", await _view(session, v))
    for t in kit.themes:
        count("theme", await _theme(session, t))
    await session.flush()
    result.themes_need_review = await _themes_needing_review(session, [t.name for t in kit.themes], actor)
    for c in kit.campaigns:
        count("campaign", await _campaign(session, c))
    for h in kit.history:
        count("application_history", await _history(session, h, actor))
    await session.flush()

    result.created = sum(created.values())
    result.updated = sum(updated.values())
    result.needs_review = sum(n for e, n in {**created, **updated}.items() if e in REVIEWED_ENTITIES) \
        if False else sum(created[e] + updated[e] for e in REVIEWED_ENTITIES)
    result.other = created + updated
    await audit.record(session, actor=actor, action="kit.imported", subject_type="kit",
                       detail={"created": dict(created), "updated": dict(updated), "excluded": sorted(exclude or ())})
    return result


async def _prompt(session: AsyncSession, p: Any) -> str:
    rows = (await session.scalars(select(Prompt).where(Prompt.stage == p.stage))).all()
    if any(r.text == p.text for r in rows):
        return "unchanged"
    taken = {r.version for r in rows}
    version = p.version if p.version not in taken else max(taken) + 1
    session.add(Prompt(stage=p.stage, text=p.text, version=version, active=False,
                       note="Imported from a kit file; activate it to use it."))
    return "created"


async def _rubric(session: AsyncSession, r: Any) -> str:
    rows = list((await session.scalars(select(Rubric).where(Rubric.name == r.name))).all())
    if not rows:
        session.add(Rubric(name=r.name, version=1, body=r.body, status=RubricStatus.draft))
        return "created"
    latest = max(rows, key=lambda x: x.version)
    if latest.body.model_dump(mode="json") == r.body.model_dump(mode="json"):
        return "unchanged"
    session.add(Rubric(family=latest.family, name=r.name, version=latest.version + 1, body=r.body,
                       status=RubricStatus.draft))
    return "updated"


async def _source(session: AsyncSession, s: Any) -> str:
    row = await session.scalar(select(Source).where(Source.connector == s.connector, Source.name == s.name))
    cols = {"access": s.access, "config": dict(s.config), "access_notes": s.access_notes,
            "rate_limit": s.rate_limit, "permitted_actions": list(s.permitted_actions)}
    if row is None:
        session.add(Source(connector=s.connector, name=s.name, enabled=False, **cols))
        return "created"
    changed = False
    for k, v in cols.items():
        cur = getattr(row, k)
        if (cur.value if hasattr(cur, "value") else cur) != v and export.plain(cur) != v \
                and not (hasattr(cur, "model_dump") and cur.model_dump(mode="json") == v.model_dump(mode="json")):
            setattr(row, k, v)
            changed = True
    return "updated" if changed else "unchanged"


async def _watched(session: AsyncSession, w: Any) -> str:
    row = await session.scalar(select(WatchedEmployer).where(
        WatchedEmployer.board_type == w.board_type, WatchedEmployer.board_slug == w.board_slug))
    cols = {"name": w.name, "priority": w.priority, "cooldown_days": w.cooldown_days,
            "always_ask_first": w.always_ask_first}
    if row is None:
        session.add(WatchedEmployer(board_type=w.board_type, board_slug=w.board_slug, **cols))
        return "created"
    if all(getattr(row, k) == v for k, v in cols.items()):
        return "unchanged"
    for k, v in cols.items():
        setattr(row, k, v)
    return "updated"


async def _alias(session: AsyncSession, model: Any, alias: str, canonical: str) -> str:
    row = await session.scalar(select(model).where(model.alias == alias))
    if row is None:
        session.add(model(alias=alias, canonical=canonical))
        return "created"
    if row.canonical == canonical:
        return "unchanged"
    row.canonical = canonical
    return "updated"


async def _tag_rule(session: AsyncSession, t: Any) -> str:
    want = t.conditions.model_dump(mode="json")
    for row in (await session.scalars(select(TagRule).where(TagRule.tag == t.tag))).all():
        if row.conditions.model_dump(mode="json") == want:
            return "unchanged"
    session.add(TagRule(tag=t.tag, conditions=t.conditions))
    return "created"


async def _facet(session: AsyncSession, f: Any) -> str:
    row = await session.scalar(select(CustomFacet).where(CustomFacet.key == f.key))
    if row is None:
        session.add(CustomFacet(key=f.key, question=f.question))
        return "created"
    if row.question == f.question:
        return "unchanged"
    row.question = f.question
    return "updated"


async def _view(session: AsyncSession, v: Any) -> str:
    row = await session.scalar(select(SavedView).where(SavedView.name == v.name))
    if row is None:
        session.add(SavedView(name=v.name, body=v.body, pinned=v.pinned))
        return "created"
    if row.body.model_dump(mode="json") == v.body.model_dump(mode="json") and row.pinned == v.pinned:
        return "unchanged"
    row.body, row.pinned = v.body, v.pinned
    return "updated"


async def _themes_needing_review(session: AsyncSession, names: list[str], actor: str) -> list[tuple[str, str]]:
    """Names of the imported themes that need review. If the active theme is one of them, the app
    goes back to the default theme (a theme that needs review is never applied)."""
    if not names:
        return []
    rows = (await session.scalars(select(Theme).where(Theme.name.in_(names), Theme.builtin.is_(False)))).all()
    flagged = [t for t in rows if theme_service.needs_review(t)]
    active = str(await settings_service.get_value(session, "appearance.theme_id"))
    if any(theme_service.api_id(t) == active for t in flagged):
        fallback = await theme_service.default_theme_id(session)
        default = await theme_service.get_theme(session, fallback)
        if default is None or theme_service.needs_review(default):
            fallback = str(REGISTRY["appearance.theme_id"].effective_default())
        await settings_service.set_value(session, "appearance.theme_id", fallback, actor=actor,
                                         reason="the active theme arrived in a Kit import and needs review")
    for t in flagged:
        await audit.record(session, actor=actor, action="theme.needs_review", subject_type="theme",
                           subject_id=t.id, detail={"name": t.name, "source": "kit_import"})
    return sorted(((theme_service.api_id(t), t.name) for t in flagged), key=lambda p: p[1].casefold())


def theme_notices(kit: KitFile) -> list[str]:
    """Preview notices for Kit themes whose body text fails the studio's contrast check."""
    return [f"Theme {t.name!r}: body text is below WCAG AA contrast. It will be imported marked "
            "'needs review' and cannot be applied until you fix or accept it in the theme studio."
            for t in kit.themes if theme_service.blocking_pairs(ThemeBody.model_validate(t.model_dump()))]


async def _theme(session: AsyncSession, t: Any) -> str:
    """Themes run the studio's token validation (``ThemeBody``) and contrast check. A Kit carries no
    contrast acceptance, so a theme whose body text fails AA lands without one: ``needs_review``."""
    rows = (await session.scalars(select(Theme).where(Theme.name == t.name, Theme.builtin.is_(False)))).all()
    body = ThemeBody.model_validate(t.model_dump())
    if not rows:
        await theme_service.create_theme(session, body, note="Imported from a Kit")
        return "created"
    same = (rows[0].light == body.light and rows[0].dark == body.dark and rows[0].radius == body.radius
            and rows[0].density == body.density and rows[0].chart == body.chart
            and rows[0].fonts.model_dump() == body.fonts.model_dump()
            and rows[0].score.model_dump() == body.score.model_dump() and rows[0].description == body.description)
    if same:
        return "unchanged"
    theme = await theme_service.update_theme(session, rows[0], body, note="Imported from a Kit")
    if theme_service.blocking_pairs(body):
        theme.contrast_waiver = None  # an earlier acceptance was for other colours
    return "updated"


def _nonempty_groups(criteria: Any) -> list[str]:
    return [g for g in CRITERIA_GROUPS if getattr(criteria, g)]


async def _campaign(session: AsyncSession, c: Any) -> str:
    track_id = None
    if c.track_key:
        track_id = await session.scalar(select(Track.id).where(Track.key == c.track_key))
    rubric_id = None
    if c.rubric_name:
        rubric = (await session.scalars(select(Rubric).where(Rubric.name == c.rubric_name)
                                        .order_by(Rubric.version.desc()).limit(1))).first()
        rubric_id = rubric.id if rubric else None
    source_ids = []
    for name in c.source_names:
        source_ids.extend((await session.scalars(select(Source.id).where(Source.name == name))).all())
    # Nothing arrives able to act: an imported automation mode above "prepare" is lowered to it.
    automation = c.automation if c.automation.mode in ("save_only", "prepare") else c.automation.model_copy(
        update={"mode": "prepare", "per_channel": {}})
    cols = {"priority": c.priority, "criteria": c.criteria, "unknown_data_policy": c.unknown_data_policy,
            "automation": automation, "track_id": track_id, "rubric_id": rubric_id,
            "source_ids": sorted(source_ids, key=str)}
    row = await session.scalar(select(Campaign).where(Campaign.name == c.name))
    if row is None:
        session.add(Campaign(name=c.name, status=CampaignStatus.draft, review_state=ReviewState.needs_review,
                             origin=Origin.imported, unconfirmed_items=_nonempty_groups(c.criteria)
                             + (["unknown_data_policy"] if any(
                                 v is not None for v in c.unknown_data_policy.model_dump().values()) else []),
                             **cols))
        return "created"
    changed_groups = [g for g in CRITERIA_GROUPS if getattr(row.criteria, g) != getattr(c.criteria, g)]
    if row.unknown_data_policy != c.unknown_data_policy:
        changed_groups.append("unknown_data_policy")
    other_changed = any(
        getattr(row, k) != v for k, v in cols.items()
        if k not in ("criteria", "unknown_data_policy", "automation", "source_ids"))
    if row.automation != automation or sorted(row.source_ids, key=str) != cols["source_ids"]:
        other_changed = True
    if not changed_groups and not other_changed:
        return "unchanged"
    for k, v in cols.items():
        setattr(row, k, v)
    row.unconfirmed_items = sorted(set(row.unconfirmed_items) | set(changed_groups))
    row.review_state, row.confirmed_at = ReviewState.needs_review, None
    return "updated"


async def _history(session: AsyncSession, h: Any, actor: str) -> str:
    key = "kit:" + hashlib.sha1(history_key(h.employer, h.title, h.applied_on).encode()).hexdigest()[:24]  # noqa: S324
    if await session.scalar(select(Application.id).where(Application.import_key == key)):
        return "unchanged"
    cand = await session.execute(select(Application, Job).join(Job, Job.id == Application.job_id)
                                 .where(Application.applied_at.is_not(None)))
    for app, job in cand.all():
        assert app.applied_at is not None
        if history_key(job.employer, job.title, app.applied_at.date()) == history_key(h.employer, h.title,
                                                                                      h.applied_on):
            return "unchanged"
    try:
        stage = Stage(h.stage)
    except ValueError:
        stage = Stage.submitted
    when = datetime.combine(h.applied_on, time(12, 0), tzinfo=utcnow().tzinfo)
    job = await corrections.create_job(
        session, title=h.title, employer=h.employer, origin="import", url=h.url,
        triage="archived" if stage in END_STAGES else "shortlisted", seen_at=when)
    if h.requisition_id:
        job.requisition_id = h.requisition_id
    app = Application(job_id=job.id, origin="import", import_key=key, stage=stage, channel=Channel(h.channel),
                      applied_at=when, owner_attested=True, applied_outside=h.channel == "manual")
    if stage in END_STAGES:
        app.ended_at = when
    session.add(app)
    await session.flush()
    await stages.add_event(session, app.id, "imported", "import",
                           {"source": "kit_file", "by": actor, "stage": stage.value})
    return "created"


def preview_counts(diff: list[DiffRow]) -> dict[str, int]:
    return dict(Counter(r.change for r in diff))
