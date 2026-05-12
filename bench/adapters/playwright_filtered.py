"""Playwright + reachability-filter reference adapter.

This adapter walks the DOM (including open shadow roots and same-origin iframes),
collects all interactable elements, and applies the seven reachability checks
defined in SPEC.md §7.3:

  1. CSS visibility (checkVisibility with opacity).
  2. Non-zero bounding rect.
  3. Disabled / aria-disabled.
  4. inert / aria-hidden cascade.
  5. pointer-events:none on self or ancestor.
  6. In-document position (off-page transform rejection).
  7. Hit-test at center after scrollIntoView (occlusion rejection).

Each element gets reachable=True/False accordingly. Elements that fail the
filter are NOT removed from the output by default — `reachable` is set to False
so the runner can score precision/recall accurately. A real consumer would call
state.find(reachable=True).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from bench.adapters._collect_js import collect_with_reachability_script
from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class PlaywrightFilteredAdapter(PerceptionAdapter):
    name = "playwright_filtered"

    def perceive(self, url: str) -> AdapterResult:
        from playwright.sync_api import sync_playwright

        start = time.perf_counter()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="load")
                page.wait_for_timeout(50)
                raw = page.evaluate(collect_with_reachability_script())
            finally:
                browser.close()
        latency_ms = (time.perf_counter() - start) * 1000

        elements = [
            PerceivedElement(
                role=e.get("role") or "",
                name=e.get("name") or "",
                reachable=bool(e.get("reachable")),
                bbox=tuple(e["bbox"]) if e.get("bbox") else None,
                extra={
                    "bench_id": e.get("bench_id"),
                    "in_shadow_dom": e.get("in_shadow_dom", False),
                    "in_iframe": e.get("in_iframe", False),
                    "tag": e.get("tag"),
                },
            )
            for e in raw
        ]

        # Compact agent-facing payload only includes reachable elements.
        reachable = [el for el in elements if el.reachable]
        agent_payload = "\n".join(
            f"@e{i+1} {el.role} \"{el.name}\""
            for i, el in enumerate(reachable)
        )

        return AdapterResult(
            adapter_name=self.name,
            url=url,
            elements=elements,
            raw_payload=agent_payload,
            captured_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            notes={
                "total_elements": len(elements),
                "reachable_count": len(reachable),
            },
        )
