"""Helpers for reading the pages manifest and ground truth."""

from __future__ import annotations

import json
import re
from pathlib import Path

from bench.types import GroundTruth, GroundTruthElement

PAGES_DIR = Path(__file__).parent / "pages"
MANIFEST_PATH = PAGES_DIR / "manifest.json"

_GROUND_TRUTH_RE = re.compile(
    r'<script\s+type="application/json"\s+id="ground-truth"\s*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def list_page_ids() -> list[str]:
    return [p["id"] for p in load_manifest()["pages"]]


def page_file(page_id: str) -> Path:
    for p in load_manifest()["pages"]:
        if p["id"] == page_id:
            return PAGES_DIR / p["file"]
    raise KeyError(f"Unknown page_id: {page_id}")


def load_ground_truth(page_id: str) -> GroundTruth:
    html = page_file(page_id).read_text()
    m = _GROUND_TRUTH_RE.search(html)
    if not m:
        raise ValueError(f"No ground-truth block found in {page_id}")
    data = json.loads(m.group(1))
    elements = [
        GroundTruthElement(
            bench_id=e["bench_id"],
            role=e["role"],
            name=e["name"],
            reachable=e["reachable"],
            reason=e.get("reason"),
            in_shadow_dom=e.get("in_shadow_dom", False),
            in_iframe=e.get("in_iframe", False),
        )
        for e in data["elements"]
    ]
    return GroundTruth(
        page_id=data["page_id"],
        category=data.get("category", ""),
        description=data.get("description", ""),
        elements=elements,
    )
