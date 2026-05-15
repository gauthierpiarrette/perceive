"""Synchronous JSON-RPC 2.0 client for MCP servers spoken over stdio.

Shared transport for the bench's MCP adapters (Playwright MCP, Chrome DevTools
MCP). Both servers speak MCP 2024-11-05 as newline-delimited JSON-RPC over a
child process's stdin/stdout; this module handles spawn, the initialize
handshake, blocking request/response, and clean teardown. It knows nothing
about any specific server's tools.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

# Protocol version we advertise. Servers may negotiate down; 2024-11-05 is the
# broadly supported baseline for the versions these servers ship at this
# writing.
MCP_PROTOCOL_VERSION = "2024-11-05"

# Override for environments where ``npx`` lives outside PATH (e.g. nvm).
_NPX_CMD = os.environ.get("PERCEIVE_NPX", "npx")

# Per-request read timeout. Tunable for slow first runs where npx downloads the
# server package (and, for some servers, a browser binary).
RPC_READ_TIMEOUT_S = float(os.environ.get("PERCEIVE_MCP_TIMEOUT", "120"))


def resolve_npx() -> str:
    """Locate the npx binary, with a helpful error if it is missing."""
    npx_path = shutil.which(_NPX_CMD)
    if npx_path is None:
        raise RuntimeError(
            f"npx not found on PATH (looked for {_NPX_CMD!r}). Install "
            "Node.js (https://nodejs.org) or set PERCEIVE_NPX to point at "
            "your npx binary."
        )
    return npx_path


class McpStdioClient:
    """One MCP server subprocess, driven synchronously.

    Use as a context manager; the subprocess is terminated cleanly on exit even
    if an exception propagates. Each request blocks until the matching response
    arrives or the read timeout fires.
    """

    def __init__(self, argv: list[str], *, read_timeout_s: float, label: str) -> None:
        self._argv = argv
        self._read_timeout_s = read_timeout_s
        self._label = label
        self._proc: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._stderr_pump: Optional[threading.Thread] = None

    def __enter__(self) -> "McpStdioClient":
        self._proc = subprocess.Popen(
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )
        # Drain stderr on a background thread; a chatty server will block our
        # stdin writes once the pipe buffer fills otherwise.
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

    # ----- MCP handshake / tool calls -----

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "perceive-bench", "version": "0"},
            },
        )
        # MCP requires this notification before tool calls become valid.
        self._notify("notifications/initialized", {})

    def call_tool(self, tool: str, arguments: dict) -> str:
        """Call an MCP tool and return its text content blocks, concatenated."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        return extract_text_blocks(result)

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
        deadline = time.monotonic() + self._read_timeout_s
        assert self._proc and self._proc.stdout
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                # readline() returns "" only on EOF.
                raise RuntimeError(
                    f"{self._label} closed stdout before responding to request "
                    f"id={req_id}. Check the Node.js / npm install."
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Some servers interleave human-readable banners with JSON-RPC.
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") != req_id:
                # Unrelated message (server-initiated notification, or a
                # response we did not ask for). Ignore.
                continue
            if "error" in msg:
                raise RuntimeError(f"{self._label} error: {msg['error']}")
            return msg.get("result", {}) or {}
        raise RuntimeError(
            f"{self._label} timed out after {self._read_timeout_s:.0f}s waiting for "
            f"response to request id={req_id}. Bump PERCEIVE_MCP_TIMEOUT if the "
            "first-run npm install is slow on this machine."
        )


def extract_text_blocks(result: dict) -> str:
    """An MCP ``tools/call`` result has a ``content`` array of typed blocks;
    concatenate the text blocks and ignore the rest."""
    content = result.get("content") or []
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(parts)
