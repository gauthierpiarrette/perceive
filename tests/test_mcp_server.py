"""End-to-end tests for the perceive MCP server (``perceive.mcp``).

The server is spawned as a real subprocess and driven over stdio with the
bench's MCP client, against the bench conformance pages.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("mcp")  # the server needs the optional [mcp] extra

from bench.adapters._mcp_stdio import McpStdioClient
from bench.manifest import PAGES_DIR
from bench.server import PagesServer

_SERVER_ARGV = [sys.executable, "-m", "perceive.mcp"]


def test_navigate_returns_reachability_filtered_snapshot():
    """`navigate` opens the page and filters unreachable elements."""
    with PagesServer(PAGES_DIR) as srv:
        url = srv.url_for("08_modal_occlusion.html")
        with McpStdioClient(_SERVER_ARGV, read_timeout_s=120, label="perceive-mcp") as client:
            client.initialize()
            snap = client.call_tool("navigate", {"url": url})
    # The modal's buttons are reachable; the buttons behind it are filtered.
    assert '"OK"' in snap and '"Cancel"' in snap
    assert "Behind" not in snap


def test_perceive_re_observes_the_current_page():
    """`perceive` re-snapshots the page opened by a prior `navigate`."""
    with PagesServer(PAGES_DIR) as srv:
        url = srv.url_for("01_display_none.html")
        with McpStdioClient(_SERVER_ARGV, read_timeout_s=120, label="perceive-mcp") as client:
            client.initialize()
            client.call_tool("navigate", {"url": url})
            snap = client.call_tool("perceive", {})
    assert '"Visible Button"' in snap
    assert "Hidden Button" not in snap


def test_click_bad_ref_is_a_graceful_error_and_server_survives():
    """A bad ref is reported as a tool error, not a server crash."""
    with PagesServer(PAGES_DIR) as srv:
        url = srv.url_for("08_modal_occlusion.html")
        with McpStdioClient(_SERVER_ARGV, read_timeout_s=120, label="perceive-mcp") as client:
            client.initialize()
            client.call_tool("navigate", {"url": url})
            # A ref that was never issued — FastMCP marks the call isError and
            # returns the message as the tool result; the server does not crash.
            result = client.call_tool("click", {"ref": "e999"})
            assert "error" in result.lower()
            # The server is still alive and usable after the error.
            snap = client.call_tool("perceive", {})
            assert '"OK"' in snap
