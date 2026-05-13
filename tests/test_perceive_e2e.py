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


def test_perceive_does_not_mutate_scroll(server):
    """Reachability checks call scrollIntoView; perceive() must restore scroll."""
    url = server.url_for("09_sticky_header_overlap.html")
    with perceive.browser(url=url) as t:
        # Start at scroll(0, 0); perceive() will scroll-into-view each candidate.
        t._page.evaluate("window.scrollTo(0, 0)")
        t.perceive()
        x, y = t._page.evaluate("[window.scrollX, window.scrollY]")
        assert (x, y) == (0, 0), f"perceive() left scroll at ({x},{y}), expected (0,0)"


def test_iframe_element_bbox_is_in_top_page_coords(server):
    """Bbox for elements inside same-origin iframes must include the iframe's offset."""
    url = server.url_for("14_iframe.html")
    with perceive.browser(url=url) as t:
        state = t.perceive()
    top = state.find(name="Top Frame Button")
    iframe_btn = state.find(name="Iframe Save")
    assert top is not None and iframe_btn is not None
    assert top.bounds is not None and iframe_btn.bounds is not None
    # The iframe sits below the top button in 14_iframe.html. With the iframe
    # offset correctly applied, the iframe button's top-frame y-coordinate
    # must be below the top button. Without the offset it would (wrongly)
    # report y ≈ 16 (just the iframe-internal padding).
    assert iframe_btn.bounds.y > top.bounds.y + 30, (
        f"iframe button bbox.y={iframe_btn.bounds.y} should be well below "
        f"top button bbox.y={top.bounds.y} — iframe offset likely not applied"
    )


def test_adding_sibling_does_not_churn_existing_refs():
    """Regression: a new sibling element must not change other elements' refs."""
    with perceive.browser() as t:
        t._page.set_content("""
            <button>Alpha</button>
            <button>Beta</button>
        """)
        s1 = t.perceive()
        alpha_ref = s1.find(name="Alpha").ref
        beta_ref = s1.find(name="Beta").ref

        # Append a third button as a sibling of the first two.
        t._page.evaluate("""
            () => {
              const b = document.createElement('button');
              b.textContent = 'Gamma';
              document.body.appendChild(b);
            }
        """)
        s2 = t.perceive()

        assert s2.find(name="Alpha").ref == alpha_ref, "Alpha's ref churned when a sibling was added"
        assert s2.find(name="Beta").ref == beta_ref, "Beta's ref churned when a sibling was added"
        assert s2.find(name="Gamma") is not None


def test_inserting_row_does_not_churn_other_rows_refs():
    """Regression: inserting a new table row must not slide other rows' Edit-button refs."""
    with perceive.browser() as t:
        t._page.set_content("""
            <table>
              <tr><td>Alice</td><td><button>Edit</button></td></tr>
              <tr><td>Bob</td><td><button>Edit</button></td></tr>
            </table>
        """)
        s1 = t.perceive()
        edits1 = s1.find_all(name="Edit")
        assert len(edits1) == 2
        original_refs = {e.ref for e in edits1}
        # The two Edit buttons must already have distinct refs.
        assert len(original_refs) == 2

        # Insert a new row at the top of the table.
        t._page.evaluate("""
            () => {
              const table = document.querySelector('table');
              const tr = document.createElement('tr');
              tr.innerHTML = '<td>Zara</td><td><button>Edit</button></td>';
              table.insertBefore(tr, table.firstElementChild);
            }
        """)
        s2 = t.perceive()
        edits2 = s2.find_all(name="Edit")
        assert len(edits2) == 3

        new_refs = {e.ref for e in edits2}
        preserved = original_refs & new_refs
        assert preserved == original_refs, (
            f"Original Edit refs {sorted(original_refs)} should all survive a row insertion, "
            f"but only {sorted(preserved)} are present (current refs: {sorted(new_refs)})"
        )


def test_iframe_click_actually_lands_on_iframe_element():
    """Regression: act('click', ref) on an iframe element must hit it, not the iframe-local origin."""
    with perceive.browser() as t:
        t._page.set_content("""
            <button style="margin-bottom: 30px">Top Button</button>
            <iframe srcdoc='
              <button onclick="parent.window.__iframe_clicked = true">In Iframe</button>
            '></iframe>
        """)
        # Let the iframe document load.
        t._page.wait_for_timeout(100)
        t._page.evaluate("window.__iframe_clicked = false")

        state = t.perceive()
        iframe_btn = state.find(name="In Iframe")
        assert iframe_btn is not None, "perceive() did not find the iframe button"

        t.act("click", iframe_btn.ref)

        fired = t._page.evaluate("window.__iframe_clicked === true")
        assert fired, (
            "Iframe button onclick did not fire — act('click') likely sent the click to the "
            "wrong top-page coordinates (frame offset not applied)."
        )


def test_perceive_does_not_mutate_nested_scroll_containers():
    """Regression: scrollIntoView on a deep element must not leave nested containers scrolled."""
    with perceive.browser() as t:
        t._page.set_content("""
            <div id="scroller" style="height:120px; width:300px; overflow:auto; border:1px solid">
              <div style="height:800px">
                <button style="margin-top:650px">Deep</button>
              </div>
            </div>
        """)
        t._page.evaluate("document.getElementById('scroller').scrollTop = 0")
        t.perceive()
        scroll_top = t._page.evaluate("document.getElementById('scroller').scrollTop")
        assert scroll_top == 0, (
            f"perceive() left a nested scroll container at scrollTop={scroll_top}; "
            "observation must restore nested scroll positions."
        )


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
