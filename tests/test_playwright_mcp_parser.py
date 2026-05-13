"""Unit tests for the Playwright MCP snapshot parser.

The parser is the only piece of the adapter that's pure Python with no
subprocess / network dependencies, so it's the right surface to pin with
fast unit tests. The subprocess + JSON-RPC path is exercised through the
bench itself (``perceive-bench run --adapter playwright_mcp``).
"""

from __future__ import annotations

from bench.adapters.playwright_mcp import _parse_snapshot


def test_parses_simple_button():
    els = _parse_snapshot('- button "Sign In" [ref=s1e2]')
    assert len(els) == 1
    el = els[0]
    assert el.role == "button"
    assert el.name == "Sign In"
    assert el.reachable is True
    assert el.bbox is None
    assert el.extra["mcp_ref"] == "s1e2"


def test_parses_yaml_indented_tree():
    snap = """\
- main [ref=s1e1]:
  - heading "Welcome" [ref=s1e2] [level=1]
  - button "Sign In" [ref=s1e3]
  - textbox "Email" [ref=s1e4]
"""
    by_name = {(e.role, e.name): e for e in _parse_snapshot(snap)}
    # `main` has no name and is structural → dropped.
    assert ("main", "") not in by_name
    # Everything with a name survives.
    assert ("heading", "Welcome") in by_name
    assert ("button", "Sign In") in by_name
    assert ("textbox", "Email") in by_name
    assert by_name["button", "Sign In"].extra["mcp_ref"] == "s1e3"


def test_drops_unnamed_structural_roles():
    snap = """\
- generic [ref=s1e1]
- group [ref=s1e2]
- list [ref=s1e3]
- button "Click" [ref=s1e4]
"""
    els = _parse_snapshot(snap)
    assert len(els) == 1
    assert els[0].name == "Click"


def test_keeps_unnamed_interactable_role():
    """An interactable role with no name (e.g. a textbox without aria-label
    that we still want to surface as a candidate) is kept, since the matcher
    can still score it on role alone."""
    els = _parse_snapshot('- textbox [ref=s1e1]')
    assert len(els) == 1
    assert els[0].role == "textbox"
    assert els[0].name == ""


def test_skips_lines_without_ref():
    snap = """\
- text: "Some content"
- button "Real" [ref=s1e1]
Banner: starting server
"""
    els = _parse_snapshot(snap)
    assert len(els) == 1
    assert els[0].name == "Real"


def test_ignores_trailing_attributes():
    """Snapshot may include extras like [level=1], [checked], etc. after [ref=...].
    We extract role+name+ref and ignore the rest."""
    el = _parse_snapshot('- checkbox "Subscribe" [ref=s1e1] [checked]')[0]
    assert el.role == "checkbox"
    assert el.name == "Subscribe"


def test_all_elements_marked_reachable():
    """Playwright MCP does not filter unreachable elements; the whole point
    of this adapter is to show that. Every element parsed must come back
    reachable=True so the bench can measure the precision gap honestly."""
    snap = """\
- button "Visible" [ref=s1e1]
- button "Hidden by display:none" [ref=s1e2]
- button "Inside inert form" [ref=s1e3]
"""
    els = _parse_snapshot(snap)
    assert len(els) == 3
    assert all(e.reachable is True for e in els)
