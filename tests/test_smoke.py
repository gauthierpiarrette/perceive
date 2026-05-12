"""Smoke tests that don't require Playwright to be installed.

Run with:  python -m pytest tests/
"""

from __future__ import annotations

import json
from pathlib import Path

from bench.manifest import (
    PAGES_DIR,
    list_page_ids,
    load_ground_truth,
    load_manifest,
)
from bench.match import match_elements
from bench.metrics import determinism_exact_match, reachability
from bench.types import AdapterResult, GroundTruthElement, PerceivedElement


def test_manifest_loads():
    manifest = load_manifest()
    assert manifest["version"] == "0.1.0"
    assert len(manifest["pages"]) == 14


def test_all_pages_exist():
    for p in load_manifest()["pages"]:
        assert (PAGES_DIR / p["file"]).is_file(), f"Missing page file: {p['file']}"


def test_every_page_has_ground_truth():
    for page_id in list_page_ids():
        gt = load_ground_truth(page_id)
        assert gt.elements, f"No ground-truth elements for {page_id}"
        for el in gt.elements:
            assert el.bench_id
            assert el.role
            assert isinstance(el.reachable, bool)


def test_ground_truth_has_both_classes():
    """At least some pages must have unreachable elements; that's the whole point."""
    saw_unreachable = False
    for page_id in list_page_ids():
        gt = load_ground_truth(page_id)
        if any(not e.reachable for e in gt.elements):
            saw_unreachable = True
            break
    assert saw_unreachable, "No page exercises unreachable elements"


# --- match.py logic ---------------------------------------------------------


def test_match_basic():
    gt = [
        GroundTruthElement(bench_id="a", role="button", name="Save", reachable=True,
                           bbox=(10.0, 10.0, 80.0, 30.0)),
        GroundTruthElement(bench_id="b", role="button", name="Delete", reachable=False,
                           bbox=(100.0, 10.0, 80.0, 30.0)),
    ]
    adapter = [
        PerceivedElement(role="button", name="Save", reachable=True,
                         bbox=(10.0, 10.0, 80.0, 30.0)),
        PerceivedElement(role="button", name="Delete", reachable=True,
                         bbox=(100.0, 10.0, 80.0, 30.0)),
    ]
    matches = match_elements(gt, adapter)
    assert len(matches) == 2
    assert matches[0].adapter is not None and matches[0].adapter.name == "Save"
    assert matches[1].adapter is not None and matches[1].adapter.name == "Delete"


def test_match_handles_missing():
    gt = [
        GroundTruthElement(bench_id="a", role="button", name="Save", reachable=True),
        GroundTruthElement(bench_id="b", role="button", name="Delete", reachable=False),
    ]
    adapter = [
        PerceivedElement(role="button", name="Save", reachable=True),
    ]
    matches = match_elements(gt, adapter)
    assert matches[1].adapter is None


# --- metrics ---------------------------------------------------------------


def test_reachability_perfect():
    from bench.types import Match
    matches = [
        Match(GroundTruthElement(bench_id="a", role="button", name="Save", reachable=True),
              PerceivedElement(role="button", name="Save", reachable=True), 1.0),
        Match(GroundTruthElement(bench_id="b", role="button", name="Delete", reachable=False),
              PerceivedElement(role="button", name="Delete", reachable=False), 1.0),
    ]
    m = reachability(matches, adapter_extras=0, page_id="t", adapter_name="x")
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.false_positive == 0


def test_reachability_baseline_failure_mode():
    """An adapter that says everything is reachable should produce false positives."""
    from bench.types import Match
    matches = [
        Match(GroundTruthElement(bench_id="a", role="button", name="OK", reachable=True),
              PerceivedElement(role="button", name="OK", reachable=True), 1.0),
        Match(GroundTruthElement(bench_id="b", role="button", name="Hidden", reachable=False),
              PerceivedElement(role="button", name="Hidden", reachable=True), 1.0),
    ]
    m = reachability(matches, adapter_extras=0, page_id="t", adapter_name="x")
    assert m.true_positive == 1
    assert m.false_positive == 1  # the costly error: agent will try to click the hidden one
    assert m.precision == 0.5


def test_determinism_identical():
    from datetime import datetime, timezone
    r = AdapterResult(
        adapter_name="x",
        url="u",
        elements=[
            PerceivedElement(role="button", name="a", reachable=True),
            PerceivedElement(role="button", name="b", reachable=False),
        ],
        raw_payload="",
        captured_at=datetime.now(timezone.utc),
        latency_ms=0.0,
    )
    assert determinism_exact_match([r, r, r]) == 1.0


def test_determinism_drifted():
    from datetime import datetime, timezone
    base = AdapterResult(
        adapter_name="x", url="u",
        elements=[PerceivedElement(role="button", name="a", reachable=True)],
        raw_payload="", captured_at=datetime.now(timezone.utc), latency_ms=0.0,
    )
    drifted = AdapterResult(
        adapter_name="x", url="u",
        elements=[PerceivedElement(role="button", name="a", reachable=False)],
        raw_payload="", captured_at=datetime.now(timezone.utc), latency_ms=0.0,
    )
    assert determinism_exact_match([base, drifted]) == 0.0
