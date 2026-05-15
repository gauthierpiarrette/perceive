"""Bench adapter that drives Google's Chrome DevTools MCP server.

chrome-devtools-mcp (github.com/ChromeDevTools/chrome-devtools-mcp) exposes a
real Chrome instance over MCP. Its ``take_snapshot`` tool returns a text view
of the page's accessibility tree — the same "raw a11y dump" pattern Playwright
MCP uses, and the same pattern ``perceive`` contrasts itself against. Running
it as a bench adapter widens the head-to-head from one competitor to two.

Requirements
============

* Node.js with ``npx`` on PATH (override via ``PERCEIVE_NPX``).
* A Chrome / Chromium install for chrome-devtools-mcp to drive.
* Network access on first run — ``npx -y chrome-devtools-mcp@latest``
  downloads the package.

Protocol
========

MCP 2024-11-05 over stdio; the transport lives in ``_mcp_stdio.py``. One
subprocess per ``perceive()`` call, matching the isolation pattern the other
adapters use. Two tool calls per perception: ``navigate_page`` then
``take_snapshot``.

Snapshot format
===============

``take_snapshot`` returns a text block headed ``## Latest page snapshot``
followed by one indented line per accessibility node::

    uid=1_0 RootWebArea "Example" url="https://example.com/"
      uid=1_3 button "Behind Button 1"
      uid=1_6 button "OK"

Each line is ``uid=<N_M> <role> "<name>"? <attr="val">*``. Roles are Chromium
AX roles: interactive ones are lowercase (``button``, ``link``), structural
ones PascalCase (``RootWebArea``, ``StaticText``). We capture every uid line,
then drop pure-structural nodes so they do not pollute the matcher.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from bench.adapters._mcp_stdio import RPC_READ_TIMEOUT_S, McpStdioClient, resolve_npx
from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class ChromeDevToolsMCPAdapter(PerceptionAdapter):
    """Runs each perception against a fresh chrome-devtools-mcp subprocess."""

    name = "chrome_devtools_mcp"

    def perceive(self, url: str) -> AdapterResult:
        start = time.perf_counter()
        # ``--isolated`` gives each subprocess a throwaway user-data-dir so
        # state does not bleed between pages or between bench runs.
        argv = [
            resolve_npx(),
            "-y",
            "chrome-devtools-mcp@latest",
            "--headless",
            "--isolated",
        ]
        with McpStdioClient(
            argv, read_timeout_s=RPC_READ_TIMEOUT_S, label="Chrome DevTools MCP"
        ) as client:
            client.initialize()
            client.call_tool("navigate_page", {"type": "url", "url": url})
            # Match the small post-load settle the other adapters use so the
            # snapshot reflects steady state (animations, modal backdrops).
            time.sleep(0.1)
            snapshot = client.call_tool("take_snapshot", {})
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


# Matches a snapshot line of the form ``uid=<N_M> <role> "<name>"? <attrs...>``.
# Leading whitespace (tree-depth indentation) is permitted; attributes after
# the optional accessible name are ignored.
_SNAPSHOT_LINE = re.compile(
    r"""
    ^\s*                            # tree-depth indentation
    uid=(?P<uid>\S+)                # uid token, e.g. 1_3
    \s+(?P<role>[A-Za-z][\w-]*)     # Chromium AX role
    (?:\s+"(?P<name>[^"]*)")?       # optional quoted accessible name
    """,
    re.VERBOSE,
)


# Chromium AX roles that never represent an interactable surface. StaticText
# and RootWebArea always carry a name, so unlike the structural roles below
# they must be dropped unconditionally.
_ALWAYS_DROP = frozenset({"rootwebarea", "statictext", "linebreak"})

# Structural containers — dropped only when they have no accessible name,
# mirroring the Playwright MCP adapter's treatment.
_STRUCTURAL_ROLES = frozenset({
    "generic", "genericcontainer", "group", "list", "listitem", "paragraph",
    "main", "navigation", "banner", "contentinfo", "complementary",
    "region", "form", "search", "document", "article", "section",
    "row", "cell", "rowgroup", "table", "columnheader", "rowheader",
})


def _parse_snapshot(snapshot: str) -> list[PerceivedElement]:
    """Parse a ``take_snapshot`` payload into PerceivedElements.

    ``reachable`` is unconditionally True: chrome-devtools-mcp's snapshot is a
    plain accessibility-tree dump with no reachability filtering — exactly the
    failure pattern this bench adapter exists to expose.
    """
    out: list[PerceivedElement] = []
    for raw_line in snapshot.splitlines():
        m = _SNAPSHOT_LINE.match(raw_line)
        if not m:
            continue
        role = m.group("role")
        name = m.group("name") or ""
        role_key = role.lower()
        if role_key in _ALWAYS_DROP:
            continue
        if role_key in _STRUCTURAL_ROLES and not name:
            continue
        out.append(
            PerceivedElement(
                role=role,
                name=name,
                reachable=True,
                bbox=None,  # take_snapshot does not expose bboxes
                extra={"cdp_uid": m.group("uid")},
            )
        )
    return out
