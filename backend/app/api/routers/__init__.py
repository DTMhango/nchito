"""All API routers, in registration order."""

from fastapi import APIRouter

from app.api.routers import (
    applications,
    assessments,
    auth,
    campaigns,
    connections,
    data,
    health,
    insights,
    interview,
    jobs,
    jobs_corrections,
    kit,
    pending_actions,
    runs,
    settings,
    sources,
    system,
    themes,
)
from app.llm import api as llm_api

ALL_ROUTERS: list[APIRouter] = [
    auth.setup_router,
    auth.router,
    settings.router,
    themes.router,
    system.router,
    health.router,
    kit.router,
    campaigns.router,
    sources.router,
    jobs.router,
    jobs_corrections.router,
    assessments.router,
    applications.router,
    pending_actions.router,
    runs.router,
    connections.connections_router,
    connections.tokens_router,
    insights.router,
    interview.router,
    data.router,
    llm_api.router,
]
