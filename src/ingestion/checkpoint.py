"""Local JSON checkpoint management: save, load, delete."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _safe_slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


def save(base_dir: str | Path, subdir: str, endpoint: str, params: dict, data) -> Path:
    """
    Write data as JSON to {base_dir}/{subdir}/{endpoint}_{param_slug}_{timestamp}.json.
    Returns the path of the written file.
    """
    checkpoint_dir = Path(base_dir) / subdir
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    param_slug = "_".join(_safe_slug(str(v)) for v in params.values()) if params else "all"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{endpoint}_{param_slug}_{timestamp}.json"

    path = checkpoint_dir / filename
    with path.open("w") as f:
        json.dump(data, f)

    return path


def load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def delete(path: Path) -> None:
    path.unlink(missing_ok=True)
