"""Theme studio (wave 4): strict token grammar incl. hostile values, contrast maths, pairs derived
from the spec, revisions/undo/redo, duplicate, default/active delete rules, import/export, kit."""

from __future__ import annotations

import json

import pytest

from app.themes.colour import contrast, oklch_to_srgb, parse_literal, srgb_to_oklch, to_hex
from app.themes.schema import ThemeBody, builtin_theme_data
from app.themes.tokens import contrast_pairs, evaluate_contrast, font_families, token_specs, valid_value
from tests.conftest import REPO


def _body(name: str = "Mine", slug: str = "copperbelt") -> dict:
    base = {k: v for k, v in next(t for t in builtin_theme_data() if t["id"] == slug).items()
            if k not in ("id", "builtin")}
    return {**base, "name": name}


HOSTILE = [
    "url(https://tracker.example/x.png)", "URL( x )", "#fff; background:red", "red}", "}", "{", "#000 }body{",
    "expression(alert(1))", "var(--x)", "var(--t-bg, url(x))", "var(--t-nope)", "var(--t-bg);", "<script>",
    "@import 'x'", "\\66 ff", "javascript:alert(1)", "rgb(1,2,3);x", "rgb(1,2,3)) , url(x)", "red",
    "#12345", "#ff\n", "inherit", "attr(data-x)", "calc(1px + 2px)", "image-set(x)", "#ff0000 !important",
]


# ---- grammar ----

@pytest.mark.nodb
@pytest.mark.parametrize("value", HOSTILE)
def test_hostile_colour_values_rejected(value):
    assert not valid_value("bg", value)
    body = _body()
    body["light"] = {**body["light"], "bg": value}
    with pytest.raises(ValueError):
        ThemeBody.model_validate(body)


@pytest.mark.nodb
@pytest.mark.parametrize("token,value", [
    ("shadow", "0 1px 2px url(x)"), ("shadow", "0 1px 2px red; color: red"), ("shadow", "0 1px"),
    ("shadow", "0 1px 2px rgba(0,0,0,.1), 0 1px 2px rgba(0,0,0,.1), 0 1px 2px #000, 0 0 1px #000, 0 0 1px #000"),
    ("display-weight", "bold"), ("display-weight", "950"), ("display-track", "1em"), ("display-track", "0.1px"),
    ("label-case", "lowercase"), ("data-font", "serif"), ("space-k", "3"), ("space-k", "1;"),
    ("elev-top", "20px"), ("elev-top", "2px }"), ("custom-thing", "url(x)"), ("custom-thing", "foo bar"),
])
def test_hostile_typed_values_rejected(token, value):
    assert not valid_value(token, value)


@pytest.mark.nodb
@pytest.mark.parametrize("token,value", [
    ("bg", "#fff"), ("bg", "#FFFFFF80"), ("bg", "rgb(10 20 30 / .5)"), ("bg", "rgba(1,2,3,.4)"),
    ("bg", "hsl(120 50% 50%)"), ("bg", "oklch(0.7 0.1 150)"), ("bg", "oklch(70% 0.1 150 / 0.5)"),
    ("panel-border", "var(--t-border-strong)"), ("shadow", "none"), ("shadow", "inset 0 1px 0 rgba(0,0,0,.1)"),
    ("shadow", "4px 4px 0 rgba(21,23,26,.12)"), ("display-weight", "650"), ("display-track", "-0.015em"),
    ("space-k", ".95"), ("elev-top", "2px"), ("custom-thing", "#123456"), ("custom-thing", "4px"),
])
def test_safe_values_accepted(token, value):
    assert valid_value(token, value)


@pytest.mark.nodb
def test_fonts_name_chart_and_score_are_strict():
    for bad in [{"fonts": {"display": "Comic Sans", "body": "Inter", "mono": "JetBrains Mono"}},
                {"fonts": {"display": "Inter;}", "body": "Inter", "mono": "JetBrains Mono"}},
                {"chart": ["#fff", "url(x)"]}, {"chart": ["var(--t-bg)"]},
                {"score": {"low": "#fff", "mid": "#000", "high": "expression(x)"}},
                {"name": "Bad\u0000name"}, {"extra": 1}]:
        with pytest.raises(ValueError):
            ThemeBody.model_validate({**_body(), **bad})


@pytest.mark.nodb
def test_every_builtin_is_valid_and_its_fonts_bundled():
    for t in builtin_theme_data():
        ThemeBody.model_validate({k: v for k, v in t.items() if k not in ("id", "builtin")})
        assert set(t["fonts"].values()) <= set(font_families())


@pytest.mark.nodb
def test_token_spec_matches_frontend_copy_and_fonts():
    front = REPO / "frontend" / "src" / "themes"
    if not front.is_dir():
        pytest.skip("frontend not present")
    ours = json.loads((REPO / "backend" / "app" / "themes" / "token_spec.json").read_text(encoding="utf-8"))
    assert json.loads((front / "token-spec.json").read_text(encoding="utf-8")) == ours
    fonts_ts = (front / "fonts.ts").read_text(encoding="utf-8")
    for family in ours["fonts"]:
        assert f'"{family}": {{' in fonts_ts or f"  {family}: {{" in fonts_ts, family


# ---- contrast maths ----

@pytest.mark.nodb
@pytest.mark.parametrize("fg,bg,expected", [
    ("#000000", "#FFFFFF", 21.0), ("#FFFFFF", "#FFFFFF", 1.0), ("#777777", "#FFFFFF", 4.48),
    ("#767676", "#FFFFFF", 4.54), ("#595959", "#FFFFFF", 7.0), ("#0000FF", "#FFFFFF", 8.59),
    ("#FF0000", "#FFFFFF", 4.0), ("#00000080", "#FFFFFF", 4.0),
])
def test_contrast_known_pairs(fg, bg, expected):
    assert contrast(parse_literal(fg), parse_literal(bg)) == pytest.approx(expected, abs=0.01)


@pytest.mark.nodb
def test_oklch_round_trip_and_known_values():
    assert to_hex((*oklch_to_srgb(1.0, 0, 0), 1)) == "#FFFFFF"
    assert to_hex((*oklch_to_srgb(0.0, 0, 0), 1)) == "#000000"
    # sRGB red is oklch(0.628 0.2577 29.23).
    lum, chroma, hue = srgb_to_oklch(1.0, 0.0, 0.0)
    assert (round(lum, 3), round(chroma, 3), round(hue, 1)) == (0.628, 0.258, 29.2)
    assert to_hex((*oklch_to_srgb(lum, chroma, hue), 1)) == "#FF0000"


@pytest.mark.nodb
def test_pairs_derive_from_spec():
    pairs = contrast_pairs()
    grounds = [k for k, v in token_specs().items() if v.get("ground")]
    assert {("text", g, "body") for g in grounds} <= set(pairs)
    assert ("primary-fg", "primary", "text") in pairs and ("warn", "warn-soft", "text") in pairs
    # Every token that declares a use produces at least one pair; nothing else does.
    used = {k for k, v in token_specs().items() if "use" in v}
    assert {p[0] for p in pairs} == used


@pytest.mark.nodb
def test_builtins_have_no_blocking_pairs_and_dim_text_blocks():
    for t in builtin_theme_data():
        for mode in ("light", "dark"):
            assert not [r for r in evaluate_contrast(t[mode], mode, t["chart"], t["score"]) if r.blocking]
    light = {**_body()["light"], "text-muted": "#B0B0B0"}
    blocking = [r for r in evaluate_contrast(light, "light") if r.blocking]
    assert blocking and {r.fg for r in blocking} == {"text-muted"} and all(not r.aa for r in blocking)


# ---- API ----

async def test_contrast_block_and_explicit_accept(owner_client):
    dim = _body("Dim")
    dim["light"] = {**dim["light"], "text": "#C8C8C8"}
    r = await owner_client.post("/api/themes", json=dim)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "theme_low_contrast" and {p["fg"] for p in detail["pairs"]} == {"text"}
    r = await owner_client.post("/api/themes", json={**dim, "accept_low_contrast": True})
    assert r.status_code == 201, r.text
    waiver = r.json()["contrast_waiver"]
    assert waiver and waiver["pairs"][0]["fg"] == "text" and waiver["accepted_by"]
    audit = (await owner_client.get("/api/audit", params={"action": "theme.contrast_accepted"})).json()
    assert len(audit["items"]) == 1
    report = (await owner_client.post("/api/themes/contrast", json=dim)).json()
    assert any(p["blocking"] and p["fg"] == "text" for p in report)


async def test_hostile_values_rejected_by_api(owner_client):
    for value in ["url(https://x.example/a.png)", "red; } body { display:none", "var(--x)", "expression(1)"]:
        body = _body()
        body["dark"] = {**body["dark"], "surface": value}
        assert (await owner_client.post("/api/themes", json=body)).status_code == 422, value


async def test_duplicate_builtin_and_builtins_immutable(owner_client):
    r = await owner_client.post("/api/themes/paper/duplicate", json={})
    assert r.status_code == 201
    copy = r.json()
    assert copy["builtin"] is False and copy["name"] == "Paper copy" and copy["revision"] == 1
    again = (await owner_client.post("/api/themes/paper/duplicate", json={})).json()
    assert again["name"] == "Paper copy (2)"
    assert (await owner_client.post("/api/themes/paper/undo")).status_code == 403
    assert (await owner_client.put("/api/themes/paper", json=_body("Paper"))).status_code == 403
    assert (await owner_client.get("/api/themes/paper")).json()["light"] == _body(slug="paper")["light"]


async def test_revisions_undo_redo_restore(owner_client):
    theme = (await owner_client.post("/api/themes", json=_body("Rev"))).json()
    tid = theme["id"]
    assert theme["can_undo"] is False
    for colour in ("#111111", "#222222"):
        body = _body("Rev")
        body["light"] = {**body["light"], "text": colour}
        r = await owner_client.put(f"/api/themes/{tid}", json=body)
        assert r.status_code == 200
    assert r.json()["revision"] == 3 and r.json()["can_undo"] is True
    r = await owner_client.post(f"/api/themes/{tid}/undo")
    assert r.json()["light"]["text"] == "#111111" and r.json()["can_redo"] is True
    r = await owner_client.post(f"/api/themes/{tid}/redo")
    assert r.json()["light"]["text"] == "#222222" and r.json()["can_redo"] is False
    assert (await owner_client.post(f"/api/themes/{tid}/redo")).status_code == 409
    r = await owner_client.post(f"/api/themes/{tid}/revisions/1/restore")
    assert r.json()["light"]["text"] == _body()["light"]["text"] and r.json()["revision"] == 1
    assert (await owner_client.post(f"/api/themes/{tid}/undo")).status_code == 409
    revs = (await owner_client.get(f"/api/themes/{tid}/revisions")).json()
    assert [x["number"] for x in revs] == [3, 2, 1] and [x["current"] for x in revs] == [False, False, True]
    # Saving from revision 1 branches; undo returns to 1, not to 3.
    body = _body("Rev renamed")
    r = await owner_client.put(f"/api/themes/{tid}", json=body)
    assert r.json()["revision"] == 4
    assert (await owner_client.get(f"/api/themes/{tid}/revisions")).json()[0]["note"] == "Renamed"
    assert (await owner_client.post(f"/api/themes/{tid}/undo")).json()["revision"] == 1


async def test_revisions_pruned_to_setting(owner_client):
    assert (await owner_client.put("/api/settings/themes.revisions_kept", json={"value": 5})).status_code == 200
    theme = (await owner_client.post("/api/themes", json=_body("Prune"))).json()
    for i in range(7):
        body = _body("Prune")
        body["light"] = {**body["light"], "text": f"#0{i}0{i}0{i}"}
        await owner_client.put(f"/api/themes/{theme['id']}", json=body)
    revs = (await owner_client.get(f"/api/themes/{theme['id']}/revisions")).json()
    assert [x["number"] for x in revs] == [8, 7, 6, 5, 4]


async def test_delete_rules_and_default(owner_client):
    theme = (await owner_client.post("/api/themes", json=_body("Def"))).json()
    tid = theme["id"]
    assert (await owner_client.put("/api/settings/themes.default_theme_id", json={"value": tid})).status_code == 409
    r = await owner_client.put(f"/api/themes/{tid}/default")
    assert r.status_code == 200 and r.json()["is_default"] is True
    listed = (await owner_client.get("/api/themes")).json()
    assert [t["id"] for t in listed if t["is_default"]] == [tid]
    assert (await owner_client.delete(f"/api/themes/{tid}")).status_code == 409
    assert (await owner_client.put("/api/themes/copperbelt/default")).status_code == 200
    assert (await owner_client.delete(f"/api/themes/{tid}")).status_code == 204
    assert (await owner_client.delete("/api/themes/copperbelt")).status_code == 403


async def test_export_import_round_trip(owner_client):
    src = (await owner_client.post("/api/themes", json={**_body("Trip", "savanna-dusk")})).json()
    exported = (await owner_client.get(f"/api/themes/{src['id']}/export")).json()
    assert exported["format"] == "nchito-theme" and exported["version"] == 1
    r = await owner_client.post("/api/themes/import", content=json.dumps(exported),
                                headers={"content-type": "application/json"})
    assert r.status_code == 201, r.text
    imported = r.json()
    assert imported["name"] == "Trip (2)"
    for key in ("fonts", "radius", "density", "light", "dark", "chart", "score", "description"):
        assert imported[key] == src[key], key
    # A bare full theme object (the old appearance export) imports too; id/builtin are ignored.
    bare = {**src, "id": "paper", "builtin": True, "name": "Bare"}
    r = await owner_client.post("/api/themes/import", content=json.dumps(bare))
    assert r.status_code == 201 and r.json()["builtin"] is False and r.json()["id"] != "paper"


async def test_import_is_strict(owner_client):
    async def post(raw: bytes | str):
        return await owner_client.post("/api/themes/import", content=raw)

    assert (await post("not json")).json()["detail"]["code"] == "invalid_theme_file"
    assert (await post("[]")).status_code == 422
    hostile = {"format": "nchito-theme", "version": 1, "theme": _body("Evil")}
    hostile["theme"]["light"] = {**hostile["theme"]["light"], "bg": "url(javascript:alert(1))"}
    r = await post(json.dumps(hostile))
    assert r.status_code == 422 and "light" in r.json()["detail"]["reason"]
    extra = {"format": "nchito-theme", "version": 1, "theme": {**_body("X"), "script": "alert(1)"}}
    assert (await post(json.dumps(extra))).status_code == 422
    assert (await owner_client.put("/api/settings/themes.import_max_bytes", json={"value": 4096})).status_code == 200
    big = {"format": "nchito-theme", "version": 1, "theme": {**_body("Big"), "description": "x" * 150},
           "pad": " " * 5000}
    assert (await post(json.dumps(big))).status_code == 413
    dim = {"format": "nchito-theme", "version": 1, "theme": _body("Dim import")}
    dim["theme"]["dark"] = {**dim["theme"]["dark"], "text": "#222222"}
    assert (await post(json.dumps(dim))).json()["detail"]["code"] == "theme_low_contrast"
    r = await owner_client.post("/api/themes/import", params={"accept_low_contrast": "true"}, content=json.dumps(dim))
    assert r.status_code == 201 and r.json()["contrast_waiver"]


async def test_themes_round_trip_through_share_setup_kit(session):
    from sqlalchemy import select

    from app.kit.export import kit_json_bytes, prepare
    from app.kit.importers.kitfile import ParsedKit, apply
    from app.kit.schema import KitFile
    from app.models.platform import Theme
    from app.themes import service

    body = ThemeBody.model_validate(_body("Kit theme", "workshop"))
    theme = await service.create_theme(session, body, actor="test")
    bundle = await prepare(session, "share_setup")
    raw = json.loads(kit_json_bytes(bundle.kit))
    assert [t["name"] for t in raw["themes"]] == ["Kit theme"]
    await session.delete(theme)
    await session.flush()

    await apply(session, ParsedKit(kit=KitFile.model_validate(raw)))
    back = await session.scalar(select(Theme).where(Theme.name == "Kit theme"))
    assert back is not None and not back.builtin
    assert service.body_of(back).model_dump() == body.model_dump()
    assert back.current_revision == 1  # imported themes start a revision history too
