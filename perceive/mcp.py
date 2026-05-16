"""MCP server for perceive.

Exposes perceive as a Model Context Protocol server, so any MCP client (Claude
Code, Claude Desktop, Cursor, ...) can drive a browser through a compact,
reachability-filtered action space.

Run it::

    pip install 'perceive[mcp]'
    perceive-mcp                     # or: python -m perceive.mcp

then point an MCP client at it over stdio.

Tools: ``navigate``, ``perceive``, ``click``, ``type``, ``scroll``, ``press``.
The action tools return a compact diff of what changed rather than a fresh
full snapshot.

The async/sync bridge
=====================

FastMCP runs an asyncio event loop and calls sync tool functions inline on the
loop thread. perceive's ``BrowserTarget`` uses Playwright's *sync* API, which
cannot run inside an asyncio loop and is thread-affine. So the ``BrowserTarget``
is confined to a single dedicated worker thread (a ``max_workers=1`` executor);
tool handlers dispatch to it via ``run_in_executor``. A side effect we rely on:
that one worker thread serializes every browser operation, so overlapping tool
calls queue cleanly with no locks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_IMPORT_ERROR: Optional[ImportError] = None
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    # Keep the module importable without the optional 'mcp' dependency. The stub
    # lets the module-level `app` and `@app.tool()` decorators below evaluate;
    # `main()` then turns the missing dependency into a clean one-line error
    # rather than an import-time traceback.
    _MCP_IMPORT_ERROR = exc

    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            pass

        def tool(self, *args, **kwargs):
            return lambda fn: fn

        def run(self, *args, **kwargs) -> None:
            pass

# Aliased: the module also defines a tool function named `perceive`, which
# would otherwise shadow this import.
import perceive as _perceive


class _BrowserWorker:
    """Owns perceive's sync ``BrowserTarget`` on one dedicated thread.

    Every browser operation is submitted to a single-thread executor: that
    thread has no asyncio loop (so sync Playwright is happy) and is the same
    thread across calls (so Playwright's thread-affinity holds). The executor
    also serializes operations — overlapping tool calls queue rather than
    corrupt the shared page state.
    """

    def __init__(self, *, headless: bool = True) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="perceive-mcp")
        self._headless = headless
        self._target: Optional[_perceive.BrowserTarget] = None
        # The most recent State, kept so an action can report a diff against
        # what the agent last saw.
        self._last: Optional[_perceive.State] = None

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, fn)

    # --- operation bodies (each runs in the worker thread) ---

    def _navigate_sync(self, url: str) -> str:
        if self._target is None:
            self._target = _perceive.browser(url=url, headless=self._headless)
        else:
            self._target.act("goto", url)
        self._last = self._target.perceive()
        return self._last.to_prompt()

    def _perceive_sync(self) -> str:
        target = self._require_target()
        self._last = target.perceive()
        return self._last.to_prompt()

    def _act_sync(self, action: str, **kwargs) -> str:
        target = self._require_target()
        before = self._last
        target.act(action, **kwargs)
        target.act("wait", 0.2)  # let the page settle before observing
        after = target.perceive()
        self._last = after
        # The diff is the compact, self-verifying result. On the first action
        # of a session (no prior snapshot) fall back to the full snapshot.
        return after.diff(before).to_prompt() if before is not None else after.to_prompt()

    def _require_target(self) -> "_perceive.BrowserTarget":
        if self._target is None:
            raise RuntimeError("No page is open. Call `navigate` first.")
        return self._target

    # --- async API used by the tools ---

    async def navigate(self, url: str) -> str:
        return await self._run(lambda: self._navigate_sync(url))

    async def perceive(self) -> str:
        return await self._run(self._perceive_sync)

    async def act(self, action: str, **kwargs) -> str:
        return await self._run(lambda: self._act_sync(action, **kwargs))

    def close(self) -> None:
        """Close the browser and stop the worker thread. Safe to call once."""
        def _shutdown() -> None:
            if self._target is not None:
                self._target.close()
                self._target = None

        try:
            self._pool.submit(_shutdown).result(timeout=10)
        except Exception:
            pass
        self._pool.shutdown(wait=True)


app = FastMCP("perceive")
_worker = _BrowserWorker()


@app.tool()
async def navigate(url: str) -> str:
    """Open a URL in the browser and return its reachability-filtered snapshot.

    The snapshot lists only elements a user could actually reach — closed
    drawers, modal-occluded controls, off-screen and inert elements are filtered
    out. Each line is ``@<ref> <role> "<name>"``; pass the ref to the
    click/type/scroll/press tools.
    """
    return await _worker.navigate(url)


@app.tool()
async def perceive() -> str:
    """Re-observe the current page and return its reachability-filtered snapshot.

    Use this when you want the full picture again; the action tools already
    return a compact diff of what they changed.
    """
    return await _worker.perceive()


@app.tool()
async def click(ref: str) -> str:
    """Click the element with the given ref (e.g. ``e3``).

    Returns a compact diff of what changed on the page.
    """
    return await _worker.act("click", ref=ref)


@app.tool(name="type")
async def type_text(ref: str, text: str) -> str:
    """Type text into the element with the given ref (e.g. ``e2``).

    Returns a compact diff of what changed on the page.
    """
    return await _worker.act("type", ref=ref, text=text)


@app.tool()
async def scroll(direction: str = "down", amount: int = 400) -> str:
    """Scroll the page. ``direction`` is up, down, left, or right.

    Returns a compact diff of what changed (often elements scrolled into reach).
    """
    return await _worker.act("scroll", direction=direction, amount=amount)


@app.tool()
async def press(key: str) -> str:
    """Press a key at the current focus (e.g. ``Enter``, ``Tab``).

    Returns a compact diff of what changed on the page.
    """
    return await _worker.act("press", key=key)


def main() -> None:
    """Entry point for the ``perceive-mcp`` console script."""
    argparse.ArgumentParser(
        prog="perceive-mcp",
        description=(
            "Run perceive as a Model Context Protocol server over stdio. "
            "Exposes a browser through perceive's reachability-filtered action "
            "space (tools: navigate, perceive, click, type, scroll, press). "
            "Launch this from an MCP client (Claude Code, Claude Desktop, "
            "Cursor) rather than running it directly; see "
            "https://github.com/gauthierpiarrette/perceive#mcp-server."
        ),
    ).parse_args()

    if _MCP_IMPORT_ERROR is not None:
        sys.stderr.write(
            "perceive-mcp requires the optional 'mcp' dependency.\n"
            "Install it with:  pip install 'perceive[mcp]'\n"
        )
        raise SystemExit(1)

    try:
        app.run("stdio")
    finally:
        _worker.close()


if __name__ == "__main__":
    main()
