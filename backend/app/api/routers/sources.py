"""Source registry, watched employers, employer aliases, trusted application sites. Wave 1 (sources stream);
trusted sites are used by wave 2 (apply)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Timestamps
from app.api.crud_db import add_db_crud
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.models.search import EmployerAlias, Source, SourceAccess, TrustedSite, WatchedEmployer
from app.pipeline import orchestrator
from app.schemas.json_types import RateLimit, SourceHealth
from app.sources.base import SearchContext, connector_class, registered_connectors
from app.sources.detect import detect
from app.sources.http import HttpxFetcher
from app.sources.registry import BOARD_TYPES, effective_config

router = APIRouter(prefix="/api", tags=["sources"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "sources"
SAMPLE_TITLES = 5

Permitted = Literal["search", "fetch", "check_open", "apply_email", "apply_browser"]


class SourceIn(ApiModel):
    connector: str = Field(description="greenhouse, lever, ashby, workable, workday, himalayas, remotive, "
                                        "weworkremotely, rss, manual, alert_email, jobspy, careers_page, web_search")
    name: str
    access: Literal["api", "feed", "html", "agent", "email"]
    config: dict[str, Any] = Field(default_factory=dict, description="Connector-specific; validated by the connector")
    access_notes: str | None = None
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    permitted_actions: list[Permitted] = Field(default_factory=lambda: ["search", "fetch", "check_open"])
    enabled: bool = True


class SourceOut(SourceIn, Timestamps):
    health: SourceHealth
    last_success_at: datetime | None = None


class SourceTestOut(BaseModel):
    ok: bool
    sample_count: int
    sample_titles: list[str]
    error: str | None = None


class DetectIn(BaseModel):
    url: str = Field(description="A careers page URL; the board type is detected")


class DetectOut(BaseModel):
    connector: str | None
    board_slug: str | None
    employer_name: str | None
    confidence: float


class WatchedEmployerIn(ApiModel):
    name: str
    board_type: str
    board_slug: str
    priority: int = 0
    cooldown_days: int | None = Field(default=None, ge=0, le=365)
    always_ask_first: bool = False


class WatchedEmployerOut(WatchedEmployerIn, Timestamps):
    pass


class WatchedEmployerFromUrl(ApiModel):
    url: str = Field(description="A careers page or posting URL; the board type and slug are detected")
    name: str | None = Field(default=None, description="Employer name; guessed from the board when omitted")
    priority: int = 0
    cooldown_days: int | None = Field(default=None, ge=0, le=365)
    always_ask_first: bool = False


class AliasIn(ApiModel):
    alias: str
    canonical: str


class AliasOut(AliasIn, Timestamps):
    pass


class TrustedSiteIn(ApiModel):
    domain: str = Field(pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$")
    system: str | None = None
    note: str | None = None


class TrustedSiteOut(TrustedSiteIn, Timestamps):
    trusted_by: str


async def prepare_trusted_site(session: Any, data: dict[str, Any], existing: TrustedSite | None) -> dict[str, Any]:
    """Only the owner edits this list (the router requires the owner); the domain is matched as a suffix."""
    data["domain"] = data["domain"].strip().lower().removeprefix("www.")
    data["trusted_by"] = "owner"
    return data


async def _prepare_source(session: Any, data: dict[str, Any], existing: Source | None) -> dict[str, Any]:
    name = data["connector"]
    if name not in registered_connectors():
        raise ValueError(f"unknown connector {name!r}; known: {', '.join(registered_connectors())}")
    cls = connector_class(name)
    if data["access"] != cls.access:
        raise ValueError(f"connector {name!r} reads by {cls.access}, not {data['access']}")
    config = dict(data["config"] or {})
    if not (name in BOARD_TYPES and not config.get("boards")):  # boards may come from the watched list
        config = cls(None).validate_config(config)  # type: ignore[call-arg,arg-type]
    data["config"] = config
    data["access"] = SourceAccess(data["access"])
    data["rate_limit"] = RateLimit.model_validate(data["rate_limit"])
    return data


async def _prepare_watched(session: Any, data: dict[str, Any], existing: WatchedEmployer | None) -> dict[str, Any]:
    if data["board_type"] not in BOARD_TYPES:
        raise ValueError(f"board_type must be one of {', '.join(BOARD_TYPES)}")
    data["board_slug"] = data["board_slug"].strip()
    data["name"] = data["name"].strip()
    if not data["board_slug"] or not data["name"]:
        raise ValueError("name and board_slug are required")
    return data


async def _ensure_source(session: Any, board_type: str) -> None:
    """A watched employer is read only through a source of its board type: make sure one exists."""
    have = await session.scalar(select(Source.id).where(Source.connector == board_type).limit(1))
    if have is not None:
        return
    cls = connector_class(board_type)
    rate = cls.default_rate_limit
    session.add(Source(connector=board_type, name=f"{board_type.title()} boards", access=SourceAccess(cls.access),
                       config={}, rate_limit=RateLimit(requests_per_minute=rate.requests_per_minute, burst=rate.burst),
                       permitted_actions=sorted(cls.permitted_actions), enabled=True))
    await session.flush()


async def _watched_after_save(session: Any, obj: WatchedEmployer) -> None:
    await _ensure_source(session, obj.board_type)


add_db_crud(router, "/sources", "sources", orm=Source, model_in=SourceIn, model_out=SourceOut,
            audit_prefix="source", order_by=[Source.created_at, Source.id], prepare=_prepare_source)
add_db_crud(router, "/watched-employers", "watched_employers", orm=WatchedEmployer, model_in=WatchedEmployerIn,
            model_out=WatchedEmployerOut, audit_prefix="watched_employer",
            order_by=[WatchedEmployer.priority.desc(), WatchedEmployer.name], prepare=_prepare_watched,
            after_save=_watched_after_save)
add_db_crud(router, "/employer-aliases", "employer_aliases", orm=EmployerAlias, model_in=AliasIn, model_out=AliasOut,
            audit_prefix="employer_alias", order_by=[EmployerAlias.canonical, EmployerAlias.alias],
            ops=("list", "create", "update", "delete"))
add_db_crud(router, "/trusted-sites", "trusted_sites", orm=TrustedSite, model_in=TrustedSiteIn,
            model_out=TrustedSiteOut, audit_prefix="trusted_site", order_by=[TrustedSite.domain],
            prepare=prepare_trusted_site, ops=("list", "create", "delete"))


def get_fetcher() -> Any:
    """The transport for detection and test-now (tests replace it through ``DEPS.transport``)."""
    deps = orchestrator.DEPS
    if deps.transport is None:
        deps.transport = HttpxFetcher()
    return deps.transport


@router.post("/sources/detect", response_model=DetectOut, name="sources_detect")
async def detect_source(body: DetectIn) -> DetectOut:
    found = await detect(get_fetcher(), body.url)
    return DetectOut(connector=found.connector, board_slug=found.board_slug, employer_name=found.employer_name,
                     confidence=found.confidence)


@router.post("/sources/{item_id}/test", response_model=SourceTestOut, name="sources_test")
async def test_source(item_id: uuid.UUID, session: SessionDep) -> SourceTestOut:
    """Search now with this source's own config and rate limit; nothing is stored."""
    source = await session.get(Source, item_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    watched = list((await session.scalars(select(WatchedEmployer))).all())
    config = effective_config(source, watched)
    deps = orchestrator.DEPS
    try:
        connector = deps.connector_for(source)
        if source.connector != "manual":
            config = connector.validate_config(config)
        ctx = SearchContext(campaign_id="test", titles=[], keywords=[], locations=[], source_config=config)
        jobs = await asyncio.wait_for(connector.search(ctx, None), timeout=deps.source_timeout_seconds)
    except Exception as exc:
        return SourceTestOut(ok=False, sample_count=0, sample_titles=[], error=f"{type(exc).__name__}: {exc}"[:500])
    return SourceTestOut(ok=True, sample_count=len(jobs), sample_titles=[j.title for j in jobs[:SAMPLE_TITLES]])


@router.post("/watched-employers/from-url", response_model=WatchedEmployerOut, status_code=status.HTTP_201_CREATED,
             name="watched_employers_from_url",
             responses={422: {"description": "The URL is not a recognised careers board"},
                        409: {"description": "That board is already watched"}})
async def watch_from_url(body: WatchedEmployerFromUrl, session: SessionDep,
                         principal: PrincipalDep) -> WatchedEmployerOut:
    """Paste a careers URL: detect the board type and slug, then add the employer to the watched list."""
    found = await detect(get_fetcher(), body.url)
    if found.connector not in BOARD_TYPES or not found.board_slug:
        raise HTTPException(422,
                            detail="That link is not a Greenhouse, Lever, Ashby, Workable or Workday board.")
    existing = await session.scalar(select(WatchedEmployer.id).where(
        WatchedEmployer.board_type == found.connector, WatchedEmployer.board_slug == found.board_slug))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already watched")
    row = WatchedEmployer(name=(body.name or found.employer_name or found.board_slug).strip(),
                          board_type=found.connector, board_slug=found.board_slug, priority=body.priority,
                          cooldown_days=body.cooldown_days, always_ask_first=body.always_ask_first)
    session.add(row)
    await session.flush()
    await _ensure_source(session, row.board_type)
    await audit.record(session, actor=principal.actor, action="watched_employer.created",
                       subject_type="watched_employer", subject_id=row.id,
                       detail={"from_url": True, "board": f"{row.board_type}:{row.board_slug}"})
    await session.refresh(row)
    return WatchedEmployerOut.model_validate(row)
