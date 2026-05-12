"""Bench adapter that wraps the `perceive` library.

This adapter calls ``perceive.browser(url).perceive(include_unreachable=True)``
and translates the resulting ``State`` to the bench's ``AdapterResult`` shape.

We pass ``include_unreachable=True`` because the bench computes precision and
recall over both classes — it needs to see what perceive *would* return as
unreachable, not what it filters out. A real consumer of perceive would either
get filtered output (default) or filter ``state.find_all(reachable=True)``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class PerceiveAdapter(PerceptionAdapter):
    name = "perceive"

    def perceive(self, url: str) -> AdapterResult:
        # Imported lazily so listing/help works without perceive installed.
        import perceive

        start = time.perf_counter()
        with perceive.browser(url=url) as target:
            state = target.perceive(include_unreachable=True)
        latency_ms = (time.perf_counter() - start) * 1000

        elements = [
            PerceivedElement(
                role=el.role,
                name=el.name,
                reachable=el.reachable,
                bbox=el.bounds.as_tuple() if el.bounds else None,
                extra={"ref": el.ref, "fingerprint": el.fingerprint},
            )
            for el in state.elements
        ]

        # The "agent payload" for token counting is the compact prompt the
        # library exposes — by default, only reachable elements.
        agent_payload = state.to_prompt()

        return AdapterResult(
            adapter_name=self.name,
            url=url,
            elements=elements,
            raw_payload=agent_payload,
            captured_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            notes={
                "total_elements": len(state.elements),
                "reachable_count": sum(1 for e in state.elements if e.reachable),
            },
        )
