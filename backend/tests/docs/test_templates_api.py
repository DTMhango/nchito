"""``GET /api/document-templates``: built-ins plus the owner's Kit templates, effective limits, defaults."""

from __future__ import annotations

from app.core.settings import service as settings_service
from app.models.kit import Template, TemplateKind, Track
from app.models.search import Campaign
from app.schemas.json_types import TemplateLimits
from tests.docs.helpers import example_spec, load_example, make_application


async def test_lists_built_ins_then_owner_templates_with_effective_limits(owner_client, session):
    r = await owner_client.get("/api/document-templates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(t["kind"], t["key"]) for t in body["templates"]] == [
        ("cv", "classic"), ("cv", "compact"), ("cv", "modern"), ("letter", "letter-plain")]
    classic = body["templates"][0]
    assert classic["builtin"] and not classic["overridden"] and classic["name"] == "Classic"
    assert classic["limits"]["pages"] == await settings_service.get_value(session, "documents.cv_pages")
    assert body["defaults"]["cv"] == {"key": "classic", "source": "setting"}

    session.add(Template(key="classic", kind=TemplateKind.cv, name="Classic, one page", html="",
                         limits=TemplateLimits(pages=1), builtin=True))
    session.add(Template(key="mine", kind=TemplateKind.cv, name="Mine", html="", builtin=False))
    await session.commit()
    await settings_service.set_value(session, "documents.letter_pages", 2, actor="owner")
    await session.commit()
    body = (await owner_client.get("/api/document-templates")).json()
    by_key = {t["key"]: t for t in body["templates"]}
    assert by_key["classic"]["overridden"] and by_key["classic"]["name"] == "Classic, one page"
    assert by_key["classic"]["limits"]["pages"] == 1
    assert by_key["mine"]["kind"] == "cv" and not by_key["mine"]["builtin"]
    assert by_key["letter-plain"]["limits"]["pages"] == 2


async def test_defaults_follow_the_applications_track(owner_client, session):
    exp = await load_example(session)
    app = await make_application(session, example_spec(exp))
    track = Track(key="tpl-track", name="Templates", cv_template="modern")
    session.add(track)
    await session.flush()
    campaign = Campaign(name="Templates", track_id=track.id)
    session.add(campaign)
    await session.flush()
    app.campaign_id = campaign.id
    await session.commit()
    body = (await owner_client.get("/api/document-templates", params={"application_id": str(app.id)})).json()
    assert body["defaults"]["cv"] == {"key": "modern", "source": "track"}
    assert body["defaults"]["letter"]["source"] == "setting"
