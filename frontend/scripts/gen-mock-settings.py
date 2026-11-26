"""Snapshot the backend settings registry for the mock backend (`npm run gen:mock-settings`).

Writes src/mocks/dataset/settings-registry.json: groups and every setting's key, label, kind,
default and bounds. Run from frontend/ with the backend installed (`pip install -e ../backend`).
"""
import json
import pathlib
import sys

here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent.parent / "backend"))

from app.core.settings.registry import GROUPS, REGISTRY  # noqa: E402

out = {"groups": [{"key": k, "label": v} for k, v in GROUPS.items()], "settings": []}
for d in REGISTRY.values():
    value = d.effective_default()
    try:
        json.dumps(value)
    except TypeError:
        value = str(value)
    out["settings"].append({
        "key": d.key, "group": d.group, "label": d.label, "description": d.description,
        "kind": str(getattr(d.kind, "value", d.kind)), "default": value, "nullable": d.nullable,
        "choices": list(d.choices) if d.choices else None, "minimum": d.minimum,
        "maximum": d.maximum, "unit": d.unit,
    })
target = here.parent / "src" / "mocks" / "dataset" / "settings-registry.json"
target.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
print(f"{len(out['settings'])} settings -> {target}")
