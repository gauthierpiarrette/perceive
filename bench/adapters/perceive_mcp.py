"""Bench adapter that drives perceive's own MCP server (``perceive.mcp``).

The other adapters here compare ``perceive`` the library against third-party
MCP servers and CLIs. This adapter closes the loop: it measures ``perceive``
*as an MCP server*, the same way Playwright MCP and Chrome DevTools MCP are
measured, so the benchmark is a true MCP-server-to-MCP-server comparison rather
than a library-versus-servers one.

Requirements
============

The ``mcp`` extra must be installed (``pip install -e ".[mcp]"`` or ``[dev]``);
the server subprocess is ``python -m perceive.mcp``.

Protocol
========

MCP 2024-11-05 over stdio; transport in ``_mcp_stdio.py``. One server
subprocess per ``perceive()`` call, matching the isolation pattern of the
other adapters. One tool call per perception: ``navigate``, which opens the
URL and returns the snapshot.

Snapshot format
===============

``navigate`` returns ``State.to_prompt()`` — one element per line::

    @e1 button "OK"
    @e2 textbox "Email" = "current value"

Each line is ``@<ref> <role> "<name>"`` with an optional ``= "<value>"`` tail.
``to_prompt()`` emits only reachable elements — perceive filters the rest
before the model ever sees them — so every parsed element is reachable, and
the unreachable ground-truth elements are simply absent (which the bench
scores as correct: they were never surfaced as actions).
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone

from bench.adapters._mcp_stdio import RPC_READ_TIMEOUT_S, McpStdioClient
from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement


class PerceiveMCPAdapter(PerceptionAdapter):
    """Runs each perception against a fresh ``perceive.mcp`` server subprocess."""

    name = "perceive_mcp"

    def perceive(self, url: str) -> AdapterResult:
        argv = [sys.executable, "-m", "perceive.mcp"]
        start = time.perf_counter()
        with McpStdioClient(
            argv, read_timeout_s=RPC_READ_TIMEOUT_S, label="perceive MCP server"
        ) as client:
            client.initialize()
            snapshot = client.call_tool("navigate", {"url": url})
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


# Matches a to_prompt() line: ``@<ref> <role> "<name>"`` with an optional
# ``= "<value>"`` tail (ignored — the matcher pairs on role + name).
_SNAPSHOT_LINE = re.compile(
    r"""
    ^\s*@(?P<ref>\S+)               # @ref
    \s+(?P<role>[A-Za-z][\w-]*)     # role
    (?:\s+"(?P<name>[^"]*)")?       # optional quoted accessible name
    """,
    re.VERBOSE,
)


def _parse_snapshot(snapshot: str) -> list[PerceivedElement]:
    """Parse a perceive-mcp ``navigate`` / ``perceive`` snapshot.

    ``reachable`` is unconditionally True: ``to_prompt()`` emits only reachable
    elements — perceive filters the rest. The bench therefore sees no
    unreachable elements from this adapter, which is exactly the point: it
    surfaces zero.
    """
    out: list[PerceivedElement] = []
    for raw_line in snapshot.splitlines():
        m = _SNAPSHOT_LINE.match(raw_line)
        if not m:
            continue
        out.append(
            PerceivedElement(
                role=m.group("role"),
                name=m.group("name") or "",
                reachable=True,
                bbox=None,  # to_prompt does not expose bboxes
                extra={"ref": m.group("ref")},
            )
        )
    return out
