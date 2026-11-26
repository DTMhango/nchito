from __future__ import annotations

import json
import re

import pytest

from app.themes.schema import COLOR_TOKENS, builtin_theme_data
from tests.conftest import REPO

SLUGS = ["copperbelt", "midnight-ledger", "savanna-dusk", "paper", "workshop", "high-contrast"]
NAMES = ["Copperbelt", "Midnight Ledger", "Savanna Dusk", "Paper", "Workshop", "High contrast"]
# The frontend corrected two mockup values for contrast; everything else is lifted verbatim.
STUDIO_KEYS = {"is_default", "revision", "can_undo", "can_redo", "contrast_waiver", "needs_review"}
MOCKUP_CORRECTIONS = {("copperbelt", "light", "text-faint"), ("savanna-dusk", "light", "text-faint")}


def _custom(name: str = "Mine") -> dict:
    base = {k: v for k, v in builtin_theme_data()[0].items() if k not in ("id", "builtin")}
    return {**base, "name": name}


async def test_list_builtins_public(client):
    themes = (await client.get("/api/themes")).json()
    assert [t["id"] for t in themes] == SLUGS
    assert [t["name"] for t in themes] == NAMES
    assert all(t["builtin"] for t in themes)
    first = themes[0]
    assert set(first) == {"id", "name", "builtin", "description", "fonts", "radius", "density", "light", "dark",
                          "chart", "score", "is_default", "revision", "can_undo", "can_redo", "contrast_waiver",
                          "needs_review"}
    assert first["is_default"] is True and not any(t["is_default"] for t in themes[1:])
    assert first["light"]["bg"] == "#F2F5F3" and first["dark"]["bg"] == "#0C1513"
    assert first["dark"]["chart-1"] == "#3FBF9A"
    assert first["score"] == {"low": "#A3B3AB", "mid": "#0F6B55", "high": "#B5673A"}


async def test_api_matches_frontend_theme_files_verbatim(client):
    themes = {t["id"]: t for t in (await client.get("/api/themes")).json()}
    folder = REPO / "frontend" / "src" / "themes" / "builtin"
    if not folder.is_dir():
        pytest.skip("frontend not present")
    for slug in SLUGS:
        expected = json.loads((folder / f"{slug}.json").read_text(encoding="utf-8"))
        expected.setdefault("description", None)
        got = {k: v for k, v in themes[slug].items()
               if (v is not None or k == "description") and k not in STUDIO_KEYS}
        got["fonts"] = {k: v for k, v in got["fonts"].items() if v is not None}
        assert got == expected, slug


@pytest.mark.nodb
def test_tokens_lifted_from_mockup():
    html = (REPO / "design" / "ui-preview.html").read_text(encoding="utf-8")
    skins = {"copperbelt": "copperbelt", "midnight": "midnight-ledger", "savanna": "savanna-dusk", "paper": "paper",
             "workshop": "workshop"}
    data = {t["id"]: t for t in builtin_theme_data()}
    for skin, slug in skins.items():
        for mode in ("light", "dark"):
            block = re.search(rf'\[data-skin="{skin}"\]\[data-mode="{mode}"\]\s*\{{(.*?)\n\}}', html, re.S)
            assert block, (skin, mode)
            decls = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block.group(1)))
            for token in COLOR_TOKENS:
                if (slug, mode, token) in MOCKUP_CORRECTIONS:
                    continue
                assert decls[token].strip() == data[slug][mode][token], (slug, mode, token)


def _luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.nodb
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_high_contrast_text_meets_aaa(mode):
    tokens = {t["id"]: t for t in builtin_theme_data()}["high-contrast"][mode]
    for ground in ["bg", "bg-sunken", "surface", "surface-2"]:
        for ink in ["text", "text-muted", "text-faint", "primary-ink", "accent-ink"]:
            assert _contrast(tokens[ink], tokens[ground]) >= 7.0, (mode, ink, ground)
    assert _contrast(tokens["primary-fg"], tokens["primary"]) >= 7.0


async def test_create_update_delete_custom(owner_client):
    r = await owner_client.post("/api/themes", json={**_custom(), "id": "my-theme"})
    assert r.status_code == 201, r.text
    theme = r.json()
    assert theme["builtin"] is False and theme["name"] == "Mine" and theme["id"] == "my-theme"
    assert (await owner_client.post("/api/themes", json={**_custom(), "id": "my-theme"})).status_code == 409
    anon = (await owner_client.post("/api/themes", json=_custom("No id"))).json()
    assert re.fullmatch(r"[0-9a-f-]{36}", anon["id"])

    theme_body = {k: v for k, v in theme.items() if k not in ("id", "builtin", *STUDIO_KEYS)}
    theme_body["light"] = {**theme_body["light"], "primary": "#123456"}
    r = await owner_client.put(f"/api/themes/{theme['id']}", json={**theme_body, "name": "Mine 2"})
    assert r.status_code == 200 and r.json()["light"]["primary"] == "#123456" and r.json()["name"] == "Mine 2"

    # The active theme cannot be deleted (409): switch away first.
    appearance = (await owner_client.get("/api/settings/appearance")).json()
    r = await owner_client.put("/api/settings/appearance", json={**appearance, "theme_id": theme["id"]})
    assert r.status_code == 200, r.text
    assert (await owner_client.delete(f"/api/themes/{theme['id']}")).status_code == 409
    r = await owner_client.put("/api/settings/appearance", json={**appearance, "theme_id": "copperbelt"})
    assert r.status_code == 200, r.text
    assert (await owner_client.delete(f"/api/themes/{theme['id']}")).status_code == 204
    assert (await owner_client.get(f"/api/themes/{theme['id']}")).status_code == 404

    audit = (await owner_client.get("/api/audit", params={"action": "theme."})).json()
    assert [a["action"] for a in audit["items"]] == ["theme.deleted", "theme.updated", "theme.created",
                                                     "theme.created"]


async def test_builtins_are_read_only(owner_client):
    assert (await owner_client.put("/api/themes/paper", json=_custom("Hijack"))).status_code == 403
    assert (await owner_client.delete("/api/themes/paper")).status_code == 403
    assert (await owner_client.get("/api/themes/paper")).json()["name"] == "Paper"


async def test_theme_validation(owner_client):
    body = _custom()
    cookies = dict(owner_client.cookies)
    owner_client.cookies.clear()
    assert (await owner_client.post("/api/themes", json=body)).status_code == 401
    owner_client.cookies.update(cookies)
    missing = {**body, "light": {k: v for k, v in body["light"].items() if k != "bg"}}
    assert (await owner_client.post("/api/themes", json=missing)).status_code == 422
    # Style tokens are optional: colour tokens alone are a valid theme.
    minimal = {**body, "light": {k: body["light"][k] for k in COLOR_TOKENS},
               "dark": {k: body["dark"][k] for k in COLOR_TOKENS}}
    assert (await owner_client.post("/api/themes", json=minimal)).status_code == 201
    unsafe = {**body, "dark": {**body["dark"], "bg": "red; } body { display:none"}}
    assert (await owner_client.post("/api/themes", json=unsafe)).status_code == 422
    url = {**body, "dark": {**body["dark"], "bg": "url(https://tracker.example/x.png)"}}
    assert (await owner_client.post("/api/themes", json=url)).status_code == 422
    assert (await owner_client.post("/api/themes", json={**body, "id": "Bad Id"})).status_code == 422
