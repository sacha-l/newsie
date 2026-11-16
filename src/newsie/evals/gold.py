"""Load a recorded gold set. Missing files yield an empty list so CI can land first."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_gold(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"gold set must be a list: {path}")
    return [row for row in payload if isinstance(row, dict)]
