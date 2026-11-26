"""A previewed import waits on disk (under ``FILES_DIR/imports/<id>/``) until the owner confirms it.

Nothing about it is written to the database before commit, so an abandoned preview leaves no trace
but a folder, removed once it is older than ``data.import_staging_hours``. Commit re-reads these
bytes and re-plans against the current database; the preview is never trusted as the plan.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.clock import utcnow


@dataclass(frozen=True)
class Staged:
    import_id: uuid.UUID
    source: str
    kit_zip: bytes | None
    history_csv: bytes | None


def _root(files_dir: Path) -> Path:
    return files_dir / "imports"


def purge(files_dir: Path, hours: int, now: datetime | None = None) -> None:
    root = _root(files_dir)
    if not root.is_dir():
        return
    cutoff = (now or utcnow()) - timedelta(hours=hours)
    for folder in root.iterdir():
        try:
            created = datetime.fromisoformat(json.loads((folder / "meta.json").read_text())["created_at"])
        except (OSError, ValueError, KeyError):
            created = cutoff
        if created <= cutoff:
            shutil.rmtree(folder, ignore_errors=True)


def stage(files_dir: Path, *, source: str, kit_zip: bytes | None, history_csv: bytes | None, hours: int) -> uuid.UUID:
    purge(files_dir, hours)
    import_id = uuid.uuid4()
    folder = _root(files_dir) / import_id.hex
    folder.mkdir(parents=True, exist_ok=True)
    if kit_zip is not None:
        (folder / "kit.zip").write_bytes(kit_zip)
    if history_csv is not None:
        (folder / "history.csv").write_bytes(history_csv)
    (folder / "meta.json").write_text(json.dumps({"source": source, "created_at": utcnow().isoformat()}))
    return import_id


def load(files_dir: Path, import_id: uuid.UUID, hours: int) -> Staged | None:
    if not re.fullmatch(r"[0-9a-f]{32}", import_id.hex):
        return None
    folder = _root(files_dir) / import_id.hex
    try:
        meta = json.loads((folder / "meta.json").read_text())
        created = datetime.fromisoformat(meta["created_at"])
    except (OSError, ValueError, KeyError):
        return None
    if created <= utcnow() - timedelta(hours=hours):
        discard(files_dir, import_id)
        return None
    kit, hist = folder / "kit.zip", folder / "history.csv"
    return Staged(import_id, meta["source"], kit.read_bytes() if kit.is_file() else None,
                  hist.read_bytes() if hist.is_file() else None)


def discard(files_dir: Path, import_id: uuid.UUID) -> None:
    shutil.rmtree(_root(files_dir) / import_id.hex, ignore_errors=True)
