"""Bench adapter that drives Vercel's agent-browser CLI.

vercel-labs/agent-browser is an accessibility-first browser automation CLI for
AI agents: it emits compact ``@eN``-style refs so agents act on a page in a few
hundred tokens instead of parsing raw HTML. Its ``snapshot`` output is still a
plain accessibility-tree dump with no reachability filtering — the same pattern
``perceive`` contrasts itself against — which is why it belongs in this bench
alongside the two MCP servers.

Requirements
============

* ``agent-browser`` on PATH (``npm i -g agent-browser``), or Node.js with
  ``npx`` as a fallback.
* The agent-browser Chrome binary, installed once via ``agent-browser install``.

Protocol
========

agent-browser keeps a browser daemon alive across CLI invocations. Each
``perceive()`` runs three commands against a named session: ``open``, then
``snapshot -i --json``, then ``close`` (so the next page is a cold launch).

Snapshot format
===============

``snapshot -i --json`` returns::

    {"success": true,
     "data": {"refs": {"e1": {"role": "button", "name": "OK"}, ...},
              "snapshot": "- button \"OK\" [ref=e1]\\n..."},
     "error": null}

``data.refs`` maps each ref id to its role and accessible name; ``data.snapshot``
is the compact agent-facing text. We build elements from ``refs`` and
token-count ``data.snapshot`` — exactly what an agent driving agent-browser
would see.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

from bench.adapters.base import PerceptionAdapter
from bench.types import AdapterResult, PerceivedElement

# Fixed session name. The bench runs pages sequentially and closes the browser
# after each, so one reused session (one daemon) is enough — no need to leak a
# fresh daemon per page.
_SESSION = "perceive-bench"

# Per-command timeout. Tunable for slow first runs (npx package download, or
# the initial browser launch).
_CMD_TIMEOUT_S = float(os.environ.get("PERCEIVE_AGENT_BROWSER_TIMEOUT", "120"))


def _resolve_cli() -> list[str]:
    """agent-browser invocation prefix.

    Prefers the installed binary; falls back to npx. A global install
    (``npm i -g agent-browser``) avoids per-command npx overhead, which matters
    because each ``perceive()`` runs three separate commands.
    """
    exe = shutil.which("agent-browser")
    if exe:
        return [exe]
    npx = shutil.which(os.environ.get("PERCEIVE_NPX", "npx"))
    if npx:
        return [npx, "-y", "agent-browser@latest"]
    raise RuntimeError(
        "agent-browser not found. Install it with `npm i -g agent-browser` "
        "(then `agent-browser install`), or install Node.js so npx is available."
    )


class AgentBrowserAdapter(PerceptionAdapter):
    """Runs each perception through the agent-browser CLI."""

    name = "agent_browser"

    def perceive(self, url: str) -> AdapterResult:
        cli = _resolve_cli()
        start = time.perf_counter()
        try:
            _run(cli, ["--session", _SESSION, "open", url])
            # Match the small post-load settle the other adapters use so the
            # snapshot reflects steady state (animations, modal backdrops).
            time.sleep(0.1)
            snapshot_json = _run(cli, ["--session", _SESSION, "snapshot", "-i", "--json"])
            latency_ms = (time.perf_counter() - start) * 1000
        finally:
            # Tear the browser down so the next page is a cold launch, even if
            # the snapshot failed. Teardown must never mask the real error.
            try:
                subprocess.run(
                    cli + ["--session", _SESSION, "close"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception:
                pass

        elements, payload = _parse_snapshot(snapshot_json)
        return AdapterResult(
            adapter_name=self.name,
            url=url,
            elements=elements,
            raw_payload=payload,
            captured_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            notes={
                "raw_lines": len(payload.splitlines()),
                "parsed_elements": len(elements),
            },
        )


# Substrings that mark a transient daemon-connect race: tearing the daemon
# down in one page's `close` can briefly outrace the next page's `open`,
# which then cannot find the daemon socket. Retrying clears it; a real
# failure (bad URL, browser crash) does not carry these markers.
_TRANSIENT_MARKERS = ("Failed to connect", "daemon may be", "os error 2")

_OPEN_RETRIES = 5


def _run(cli: list[str], args: list[str]) -> str:
    """Run one agent-browser command, returning stdout.

    Retries the transient daemon-connect race described at `_TRANSIENT_MARKERS`;
    raises on any other non-zero exit.
    """
    for attempt in range(_OPEN_RETRIES + 1):
        proc = subprocess.run(
            cli + args,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT_S,
        )
        if proc.returncode == 0:
            return proc.stdout
        detail = proc.stderr.strip() or proc.stdout.strip()
        transient = any(marker in detail for marker in _TRANSIENT_MARKERS)
        if transient and attempt < _OPEN_RETRIES:
            time.sleep(0.5 * (attempt + 1))
            continue
        raise RuntimeError(
            f"agent-browser {' '.join(args)} failed (exit {proc.returncode}): {detail}"
        )


def _parse_snapshot(snapshot_json: str) -> tuple[list[PerceivedElement], str]:
    """Parse ``snapshot -i --json`` output into (elements, agent-facing payload).

    ``reachable`` is unconditionally True: agent-browser emits a plain
    accessibility-tree snapshot with no reachability filtering — exactly the
    failure pattern this bench adapter exists to expose.
    """
    try:
        doc = json.loads(snapshot_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"agent-browser snapshot returned non-JSON output: {e}")
    if not doc.get("success"):
        raise RuntimeError(f"agent-browser snapshot error: {doc.get('error')}")

    data = doc.get("data") or {}
    refs = data.get("refs") or {}
    payload = data.get("snapshot") or ""

    elements: list[PerceivedElement] = []
    for ref_id, info in refs.items():
        elements.append(
            PerceivedElement(
                role=(info or {}).get("role") or "",
                name=(info or {}).get("name") or "",
                reachable=True,
                bbox=None,  # snapshot does not expose bboxes
                extra={"agent_browser_ref": ref_id},
            )
        )
    return elements, payload
