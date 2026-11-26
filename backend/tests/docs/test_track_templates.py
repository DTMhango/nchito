"""Template choice per track: the campaign track's template wins; null falls back to the documents setting."""

from __future__ import annotations

from app.core.settings import service as settings_service
from app.docs import service
from app.models.kit import Track
from app.models.search import Campaign
from tests.docs.helpers import example_spec, load_example, make_application


async def test_track_template_overrides_the_setting_and_null_falls_back(session):
    exp = await load_example(session)
    app = await make_application(session, example_spec(exp))
    assert (await service.prepare(session, app, "cv")).template.key == "classic"  # the setting's default

    track = Track(key="analytics-tpl", name="Analytics", cv_template="compact", letter_template=None)
    session.add(track)
    await session.flush()
    campaign = Campaign(name="Templates", track_id=track.id)
    session.add(campaign)
    await session.flush()
    app.campaign_id = campaign.id
    await session.flush()
    assert (await service.prepare(session, app, "cv")).template.key == "compact"
    await settings_service.set_value(session, "documents.letter_template", "letter-plain", actor="owner")
    assert (await service.prepare(session, app, "letter")).template.key == "letter-plain"  # null on the track
    assert (await service.prepare(session, app, "cv", "modern")).template.key == "modern"  # explicit choice wins
