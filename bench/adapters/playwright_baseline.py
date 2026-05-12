"""Playwright baseline adapter.

This adapter returns every interactable element it can discover via DOM walking,
with `reachable=True` for every element. It does NOT apply any reachability
filtering. The purpose of this adapter is to demonstrate, in concrete numbers,
the problem documented in Playwright issue #39955 — accessibility-tree-style
output that includes elements an agent cannot actually interact with.

It is the strawman the `perceive` library must beat.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from bench.adapters._collect_js import collect_interactables_script
from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class PlaywrightBaselineAdapter(PerceptionAdapter):
    name = "playwright_baseline"

    def perceive(self, url: str) -> AdapterResult:
        # Imported lazily so listing/help works without playwright installed.
        from playwright.sync_api import sync_playwright

        start = time.perf_counter()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="load")
                # Give web components / shadow DOM a tick to attach.
                page.wait_for_timeout(50)
                raw = page.evaluate(collect_interactables_script())
            finally:
                browser.close()
        latency_ms = (time.perf_counter() - start) * 1000

        elements = [
            PerceivedElement(
                role=e.get("role") or "",
                name=e.get("name") or "",
                # Baseline: NO filtering. Every interactable is reported reachable.
                reachable=True,
                bbox=tuple(e["bbox"]) if e.get("bbox") else None,
                extra={
                    "bench_id": e.get("bench_id"),
                    "in_shadow_dom": e.get("in_shadow_dom", False),
                    "in_iframe": e.get("in_iframe", False),
                    "tag": e.get("tag"),
                    "disabled": e.get("disabled", False),
                },
            )
            for e in raw
        ]

        # Compact agent-facing payload, mirroring how raw a11y dumps are typically
        # shown to a model.
        agent_payload = "\n".join(
            f"@e{i+1} {el.role} \"{el.name}\""
            for i, el in enumerate(elements)
        )

        return AdapterResult(
            adapter_name=self.name,
            url=url,
            elements=elements,
            raw_payload=agent_payload,
            captured_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            notes={"raw_element_count": len(raw)},
        )
