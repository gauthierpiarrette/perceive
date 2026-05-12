"""End-to-end tests that drive a real Chromium against the bench pages."""

from __future__ import annotations

import pytest

import perceive
from bench.manifest import PAGES_DIR
from bench.server import PagesServer


@pytest.fixture(scope="module")
def server():
    with PagesServer(PAGES_DIR) as s:
        yield s


def test_perceive_basic_page(server):
    url = server.url_for("01_display_none.html")
    with perceive.browser(url=url) as t:
        state = t.perceive()
    # default behaviour filters unreachable → only the visible button.
    names = sorted(e.name for e in state.elements)
    assert names == ["Visible Button"]


def test_include_unreachable_returns_both(server):
    url = server.url_for("01_display_none.html")
    with perceive.browser(url=url) as t:
        state = t.perceive(include_unreachable=True)
    by_name = {e.name: e for e in state.elements}
    assert by_name["Visible Button"].reachable is True
    assert by_name["Hidden Button"].reachable is False


def test_refs_are_stable_across_two_perceives(server):
    """Same page, same elements, same refs."""
    url = server.url_for("12_disabled_controls.html")
    with perceive.browser(url=url) as t:
        s1 = t.perceive(include_unreachable=True)
        s2 = t.perceive(include_unreachable=True)
    refs1 = {e.name: e.ref for e in s1.elements}
    refs2 = {e.name: e.ref for e in s2.elements}
    assert refs1 == refs2


def test_diff_after_no_action_is_empty(server):
    url = server.url_for("01_display_none.html")
    with perceive.browser(url=url) as t:
        s1 = t.perceive()
        s2 = t.perceive()
    assert s2.diff(s1).empty


def test_to_prompt_only_emits_reachable(server):
    url = server.url_for("08_modal_occlusion.html")
    with perceive.browser(url=url) as t:
        state = t.perceive()
    out = state.to_prompt()
    # The modal buttons are reachable, the behind buttons are not.
    assert '"OK"' in out
    assert '"Cancel"' in out
    assert "Behind" not in out


def test_observe_change_captures_diff(server):
    """observe_change() exposes before/after/diff after the block runs."""
    url = server.url_for("13_shadow_dom.html")
    with perceive.browser(url=url) as t:
        with t.observe_change() as obs:
            # No actions — diff should be empty but populated.
            pass
        assert obs.before is not None
        assert obs.after is not None
        assert obs.diff is not None
        assert obs.diff.empty
