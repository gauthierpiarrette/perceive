"""Bench adapter that drives Microsoft's Playwright MCP server.

Playwright MCP is the canonical reference for the "raw accessibility tree
snapshot" pattern that ``perceive`` contrasts itself against. Running it as a
bench adapter gives us a head-to-head comparison on the same conformance
pages: every false positive Playwright MCP produces is a documented instance
of the failure pattern from Playwright issue #39955.

Requirements
============

* Node.js with ``npx`` on PATH (override via ``PERCEIVE_NPX``).
* Network access on first run — ``npx -y @playwright/mcp@latest`` downloads
  the package and (transitively) the Playwright browsers it needs.

Protocol
========

MCP 2024-11-05 over stdio; the transport lives in ``_mcp_stdio.py``. One
subprocess per ``perceive()`` call, matching the isolation pattern the other
adapters use (each launches its own Chromium per page). Two tool calls per
perception: ``browser_navigate`` then ``browser_snapshot``.

Snapshot format
===============

The ``browser_snapshot`` tool returns a YAML-ish aria tree. Each interactable
element is a line of the shape::

    - <role> "<name>" [ref=<id>] [<extras...>]

We parse liberally: any line with a ``[ref=...]`` tag is captured. Lines
without an accessible name whose role is purely structural (``generic``,
``main``, ``list``, …) are dropped so they do not pollute the matcher.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from bench.adapters._mcp_stdio import RPC_READ_TIMEOUT_S, McpStdioClient, resolve_npx
from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class PlaywrightMCPAdapter(PerceptionAdapter):
    """Runs each perception against a fresh Playwright MCP subprocess."""

    name = "playwright_mcp"

    def perceive(self, url: str) -> AdapterResult:
        start = time.perf_counter()
        # ``--isolated`` gives each subprocess its own browser profile so state
        # does not bleed between pages or between bench runs.
        argv = [
            resolve_npx(),
            "-y",
            "@playwright/mcp@latest",
            "--headless",
            "--isolated",
        ]
        with McpStdioClient(
            argv, read_timeout_s=RPC_READ_TIMEOUT_S, label="Playwright MCP"
        ) as client:
            client.initialize()
            client.call_tool("browser_navigate", {"url": url})
            # Many pages animate post-load (sticky headers settling, modal
            # backdrops fading in). Match the small wait the other adapters
            # use in collect() so the snapshot reflects steady state.
            time.sleep(0.1)
            snapshot = client.call_tool("browser_snapshot", {})
        latency_ms = (time.perf_counter() - start) * 1000

        elements = _parse_snapshot(snapshot)
        return AdapterResult(
            adapter_name=self.name,
            url=url,
            elements=elements,
            raw_payload=snapshot,
            captured_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            notes={
                "raw_lines": len(snapshot.splitlines()),
                "parsed_elements": len(elements),
            },
        )


# ----- snapshot parser -----


# Matches a line of the form ``- <role> "<name>"? [ref=<id>] [<extras...>]?``.
# Indentation (any amount of leading whitespace) is permitted; trailing
# attributes after the ``[ref=...]`` tag are ignored.
_SNAPSHOT_LINE = re.compile(
    r"""
    ^\s*-\s+                       # YAML-ish list marker
    (?P<role>[A-Za-z][\w-]*)       # role (alphanumeric / hyphen)
    (?:\s+"(?P<name>[^"]*)")?      # optional accessible name in quotes
    \s+\[ref=(?P<ref>[^\]]+)\]     # required ref tag
    """,
    re.VERBOSE,
)


# Structural roles that carry no actionable surface; we drop these when they
# lack an accessible name so they do not show up as "elements" the matcher
# tries to pair with conformance ground-truth (which is all interactables).
_STRUCTURAL_ROLES = frozenset({
    "generic", "group", "list", "listitem", "paragraph",
    "main", "navigation", "banner", "contentinfo", "complementary",
    "region", "form", "search", "document", "article", "section",
    "row", "cell", "rowgroup", "table", "columnheader", "rowheader",
})


def _parse_snapshot(snapshot: str) -> list[PerceivedElement]:
    """Parse a ``browser_snapshot`` payload into PerceivedElements.

    ``reachable`` is unconditionally True: Playwright MCP's accessibility
    snapshot does not perform reachability filtering — that is the very
    failure pattern from Playwright issue #39955 we want this bench adapter
    to expose.
    """
    out: list[PerceivedElement] = []
    for raw_line in snapshot.splitlines():
        m = _SNAPSHOT_LINE.match(raw_line)
        if not m:
            continue
        role = m.group("role")
        name = m.group("name") or ""
        ref = m.group("ref")
        if role in _STRUCTURAL_ROLES and not name:
            continue
        out.append(
            PerceivedElement(
                role=role,
                name=name,
                reachable=True,
                bbox=None,  # MCP snapshot does not expose bboxes
                extra={"mcp_ref": ref},
            )
        )
    return out
