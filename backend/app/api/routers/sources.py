"""Source registry, watched employers, employer aliases, trusted application sites. Wave 1 (sources stream);
trusted sites are used by wave 2 (apply)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import RequireOwner
from app.schemas.json_types import RateLimit, SourceHealth

router = APIRouter(prefix="/api", tags=["sources"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "sources"

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


add_crud(router, "/sources", "sources", SourceIn, SourceOut, wave=WAVE, area=AREA)
add_crud(router, "/watched-employers", "watched_employers", WatchedEmployerIn, WatchedEmployerOut,
         wave=WAVE, area=AREA)
add_crud(router, "/employer-aliases", "employer_aliases", AliasIn, AliasOut, wave=WAVE, area=AREA,
         ops=("list", "create", "update", "delete"))
add_crud(router, "/trusted-sites", "trusted_sites", TrustedSiteIn, TrustedSiteOut, wave=2, area="apply",
         ops=("list", "create", "delete"))


@router.post("/sources/{item_id}/test", response_model=SourceTestOut, name="sources_test")
async def test_source(item_id: uuid.UUID) -> SourceTestOut:
    not_implemented(WAVE, AREA)


@router.post("/sources/detect", response_model=DetectOut, name="sources_detect")
async def detect_source(body: DetectIn) -> DetectOut:
    not_implemented(WAVE, AREA)
