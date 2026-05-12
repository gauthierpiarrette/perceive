"""Suite runners — orchestrate adapter calls, ground-truth matching, and metrics."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.adapters import get_adapter
from bench.adapters._collect_js import bench_id_bboxes_script
from bench.manifest import PAGES_DIR, load_ground_truth, list_page_ids
from bench.match import match_elements
from bench.metrics import (
    ReachabilityMetrics,
    determinism_exact_match,
    reachability,
    token_count,
)
from bench.server import PagesServer
from bench.types import AdapterResult, GroundTruth


# --- helpers --------------------------------------------------------------


def _attach_ground_truth_bboxes(gt: GroundTruth, url: str) -> None:
    """Use Playwright to fetch each [data-bench-id] element's actual bbox on the page.

    Mutates GroundTruthElement.bbox in-place. Cheap — one extra Chromium open.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_timeout(50)
            raw = page.evaluate(bench_id_bboxes_script())
        finally:
            browser.close()

    by_id = {r["bench_id"]: tuple(r["bbox"]) for r in raw if r.get("bench_id")}
    for el in gt.elements:
        if el.bench_id in by_id:
            el.bbox = by_id[el.bench_id]


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# --- suites ---------------------------------------------------------------


def run_reachability(
    adapter_name: str,
    page_ids: list[str],
) -> dict:
    adapter = get_adapter(adapter_name)
    results_per_page: list[dict] = []

    with PagesServer(PAGES_DIR) as server:
        for page_id in page_ids:
            url = server.url_for(_filename_for(page_id))
            gt = load_ground_truth(page_id)
            _attach_ground_truth_bboxes(gt, url)

            adapter_result = adapter.perceive(url)
            matches = match_elements(gt.elements, adapter_result.elements)
            # Adapter elements that did not match any ground-truth element.
            matched_adapter_idxs = {id(m.adapter) for m in matches if m.adapter is not None}
            extras = sum(1 for el in adapter_result.elements if id(el) not in matched_adapter_idxs)

            metrics = reachability(
                matches=matches,
                adapter_extras=extras,
                page_id=page_id,
                adapter_name=adapter_name,
            )
            results_per_page.append(
                {
                    "page_id": page_id,
                    "category": gt.category,
                    "metrics": metrics.to_dict(),
                    "match_details": [
                        {
                            "bench_id": m.bench.bench_id,
                            "expected_reachable": m.bench.reachable,
                            "matched": m.adapter is not None,
                            "adapter_reachable": (m.adapter.reachable if m.adapter else None),
                            "score": m.score,
                        }
                        for m in matches
                    ],
                }
            )

    return _summarize_reachability(adapter_name, results_per_page)


def run_tokens(adapter_name: str, page_ids: list[str]) -> dict:
    adapter = get_adapter(adapter_name)
    rows = []
    with PagesServer(PAGES_DIR) as server:
        for page_id in page_ids:
            url = server.url_for(_filename_for(page_id))
            r = adapter.perceive(url)
            rows.append(
                {
                    "page_id": page_id,
                    "adapter": adapter_name,
                    "elements_emitted": len(r.elements),
                    "elements_in_payload": r.raw_payload.count("\n") + (1 if r.raw_payload else 0),
                    "tokens": token_count(r.raw_payload),
                    "latency_ms": round(r.latency_ms, 1),
                }
            )
    return {
        "adapter": adapter_name,
        "pages": rows,
        "summary": {
            "median_tokens": _median([r["tokens"] for r in rows]),
            "p95_tokens": _percentile([r["tokens"] for r in rows], 95),
            "median_latency_ms": _median([r["latency_ms"] for r in rows]),
        },
    }


def run_determinism(adapter_name: str, page_ids: list[str], runs: int) -> dict:
    adapter = get_adapter(adapter_name)
    out = []
    with PagesServer(PAGES_DIR) as server:
        for page_id in page_ids:
            url = server.url_for(_filename_for(page_id))
            results: list[AdapterResult] = []
            for _ in range(runs):
                results.append(adapter.perceive(url))
            rate = determinism_exact_match(results)
            out.append(
                {
                    "page_id": page_id,
                    "runs": runs,
                    "exact_match_rate": rate,
                    "element_counts": [len(r.elements) for r in results],
                }
            )
    return {
        "adapter": adapter_name,
        "pages": out,
        "summary": {
            "mean_exact_match_rate": _mean([r["exact_match_rate"] for r in out]),
        },
    }


# --- summarization --------------------------------------------------------


def _summarize_reachability(adapter_name: str, page_rows: list[dict]) -> dict:
    tps = sum(p["metrics"]["true_positive"] for p in page_rows)
    fps = sum(p["metrics"]["false_positive"] for p in page_rows)
    tns = sum(p["metrics"]["true_negative"] for p in page_rows)
    fns = sum(p["metrics"]["false_negative"] for p in page_rows)
    missed = sum(p["metrics"]["missed"] for p in page_rows)

    precision = tps / (tps + fps) if (tps + fps) else 0.0
    recall = tps / (tps + fns) if (tps + fns) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "adapter": adapter_name,
        "pages": page_rows,
        "summary": {
            "n_pages": len(page_rows),
            "true_positive": tps,
            "false_positive": fps,
            "true_negative": tns,
            "false_negative": fns,
            "missed": missed,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
    }


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(xs: list[float], p: int) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = int(round((p / 100) * (len(s) - 1)))
    return s[k]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _filename_for(page_id: str) -> str:
    from bench.manifest import load_manifest

    for p in load_manifest()["pages"]:
        if p["id"] == page_id:
            return p["file"]
    raise KeyError(page_id)


# --- output ---------------------------------------------------------------


def write_results_json(name: str, payload: dict) -> Path:
    out_dir = Path(__file__).parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{name}_{stamp}.json"
    path.write_text(json.dumps(_to_jsonable(payload), indent=2))
    return path


def resolve_page_ids(spec: str | None) -> list[str]:
    """Parse a CLI --pages spec: 'all', a comma list, or a single id."""
    all_ids = list_page_ids()
    if spec is None or spec == "all":
        return all_ids
    requested = [s.strip() for s in spec.split(",") if s.strip()]
    invalid = [r for r in requested if r not in all_ids]
    if invalid:
        raise ValueError(f"Unknown page ids: {invalid}. Available: {all_ids}")
    return requested
