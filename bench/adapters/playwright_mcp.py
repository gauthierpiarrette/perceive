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

* MCP 2024-11-05, JSON-RPC 2.0 over stdio, newline-delimited messages.
* One subprocess per ``perceive()`` call, matching the isolation pattern the
  other adapters use (each launches its own Chromium per page).
* Two tool calls per call: ``browser_navigate`` then ``browser_snapshot``.

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

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement

# Protocol version we tell the server we speak. The server is free to
# negotiate down; for the versions Playwright MCP ships at this writing,
# 2024-11-05 is the broadly supported baseline.
_MCP_PROTOCOL_VERSION = "2024-11-05"

# Override for environments where ``npx`` lives outside PATH (e.g. nvm).
_NPX_CMD = os.environ.get("PERCEIVE_NPX", "npx")

# Tunable for slow first-runs (the npx download + Playwright browser install
# can blow past the default). Per-request, not per-session.
_RPC_READ_TIMEOUT_S = float(os.environ.get("PERCEIVE_MCP_TIMEOUT", "120"))


class PlaywrightMCPAdapter(PerceptionAdapter):
    """Runs each perception against a fresh Playwright MCP subprocess."""

    name = "playwright_mcp"

    def perceive(self, url: str) -> AdapterResult:
        start = time.perf_counter()
        with _PlaywrightMCPClient() as client:
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


# ----- MCP stdio JSON-RPC client -----


class _PlaywrightMCPClient:
    """Synchronous JSON-RPC client for one Playwright MCP subprocess.

    Use as a context manager; the subprocess is terminated cleanly on exit
    even if an exception propagates. Each request blocks until the matching
    response arrives or the read timeout fires.
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._stderr_pump: Optional[threading.Thread] = None

    def __enter__(self) -> "_PlaywrightMCPClient":
        npx_path = shutil.which(_NPX_CMD)
        if npx_path is None:
            raise RuntimeError(
                f"npx not found on PATH (looked for {_NPX_CMD!r}). Install "
                "Node.js (https://nodejs.org) or set PERCEIVE_NPX to point at "
                "your npx binary."
            )
        # ``--isolated`` gives each subprocess its own browser profile so
        # state does not bleed between pages or between bench runs.
        self._proc = subprocess.Popen(
            [
                npx_path,
                "-y",
                "@playwright/mcp@latest",
                "--headless",
                "--isolated",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )
        # Drain stderr on a background thread; a chatty server will block
        # stdin writes once the pipe fills otherwise.
        def _pump() -> None:
            assert self._proc and self._proc.stderr
            try:
                for _ in self._proc.stderr:
                    pass
            except Exception:
                pass

        self._stderr_pump = threading.Thread(target=_pump, daemon=True)
        self._stderr_pump.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        except Exception:
            pass
        self._proc = None

    # ----- JSON-RPC primitives -----

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "perceive-bench", "version": "0.2.1"},
            },
        )
        # MCP requires this notification before tool calls become valid.
        self._notify("notifications/initialized", {})

    def call_tool(self, tool: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        return _extract_text_blocks(result)

    # ----- wire format -----

    def _request(self, method: str, params: dict) -> dict:
        req_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return self._wait_for_response(req_id)

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, msg: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _wait_for_response(self, req_id: int) -> dict:
        deadline = time.monotonic() + _RPC_READ_TIMEOUT_S
        assert self._proc and self._proc.stdout
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                # readline() returns "" only on EOF.
                raise RuntimeError(
                    f"Playwright MCP closed stdout before responding to request "
                    f"id={req_id}. Check Node.js / @playwright/mcp install."
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Some servers interleave human-readable banners with JSON-RPC.
                # Skip lines we cannot parse rather than aborting the run.
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") != req_id:
                # Unrelated message (server-initiated notification or other
                # response we have not asked for). Ignore.
                continue
            if "error" in msg:
                raise RuntimeError(f"Playwright MCP error: {msg['error']}")
            return msg.get("result", {}) or {}
        raise RuntimeError(
            f"Playwright MCP timed out after {_RPC_READ_TIMEOUT_S:.0f}s waiting for "
            f"response to request id={req_id}. Bump PERCEIVE_MCP_TIMEOUT if the "
            "first-run @playwright/mcp install is slow on this machine."
        )


def _extract_text_blocks(result: dict) -> str:
    """An MCP ``tools/call`` result has a ``content`` array of typed blocks;
    we concatenate the text blocks and ignore the rest."""
    content = result.get("content") or []
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(parts)


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
