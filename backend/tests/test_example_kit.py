from __future__ import annotations

import hashlib
import json
import re

import pytest
from pydantic import ValidationError

from app.kit.schema import KitFile
from tests.conftest import REPO

pytestmark = pytest.mark.nodb

KIT_DIR = REPO / "kits" / "example"


def _raw() -> dict:
    return json.loads((KIT_DIR / "kit.json").read_text(encoding="utf-8"))


def test_example_kit_is_valid_and_covers_every_entity():
    kit = KitFile.model_validate(_raw())
    assert kit.kind == "personal_backup"
    for name, field in KitFile.model_fields.items():
        if name in ("schema_version", "kind", "exported_at", "app_version"):
            continue
        value = getattr(kit, name)
        assert value, f"example kit does not cover {name}"
    assert {g.params.type for g in kit.guardrails} == {
        "never_mention", "never_together", "require_wording", "reframe", "omit_field", "format", "positioning",
        "limit", "attach_policy"}
    assert {a.answer_class for a in kit.answers} == {"auto", "ask_first", "never", "owner_only"}
    assert any(f.keep_out_of_prompts for f in kit.facts)


def test_vault_files_match_their_hashes():
    kit = KitFile.model_validate(_raw())
    for doc in kit.vault:
        data = (KIT_DIR / doc.path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == doc.sha256


def test_example_kit_is_clearly_fictional():
    text = (KIT_DIR / "kit.json").read_text(encoding="utf-8")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text))
    assert emails and all(e.endswith("@example.com") for e in emails)
    urls = set(re.findall(r"https?://([^/\"]+)", text))
    assert all(u.endswith(("example.com", "linkedin.com", "github.com")) for u in urls), urls


def test_share_setup_rejects_personal_sections():
    raw = _raw()
    raw["kind"] = "share_setup"
    with pytest.raises(ValidationError, match="personal sections"):
        KitFile.model_validate(raw)
    shared = {k: v for k, v in raw.items() if k not in
              ("person", "experiences", "facts", "skills", "references", "answers", "vault", "history")}
    shared["tracks"] = [{**t, "lead_fact_codes": [], "summary_fact_code": None} for t in raw["tracks"]]
    assert KitFile.model_validate(shared).kind == "share_setup"


def test_cross_references_checked():
    raw = _raw()
    raw["facts"][1]["experience_ref"] = "nowhere"
    with pytest.raises(ValidationError, match="unknown experience_ref"):
        KitFile.model_validate(raw)
    raw = _raw()
    raw["campaigns"][0]["rubric_name"] = "missing"
    with pytest.raises(ValidationError, match="unknown rubric"):
        KitFile.model_validate(raw)
