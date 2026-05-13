"""Unit tests for perceive: types, refs, diff, prompt. No browser required."""

from __future__ import annotations

from datetime import datetime, timezone

from perceive import DiffResult, Element, State
from perceive._refs import Features, RefAllocator
from perceive.types import Bounds


# ----- Bounds -----


def test_bounds_center():
    b = Bounds(10.0, 20.0, 100.0, 40.0)
    assert b.cx == 60.0
    assert b.cy == 40.0
    assert b.as_tuple() == (10.0, 20.0, 100.0, 40.0)


# ----- Features.fingerprint -----


def _feat(**kw):
    base = dict(
        role="", name="", aria_label="", test_id="", id_attr="",
        name_attr="", href="", parent_landmark="", row_context="",
    )
    base.update(kw)
    return Features(**base)


def test_fingerprint_stable_for_same_features():
    a = _feat(role="button", name="Save", id_attr="save-btn")
    b = _feat(role="button", name="Save", id_attr="save-btn")
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_changes_when_identity_changes():
    a = _feat(role="button", name="Save")
    b = _feat(role="button", name="Cancel")
    assert a.fingerprint() != b.fingerprint()


# ----- RefAllocator -----


def test_refs_are_stable_across_calls():
    alloc = RefAllocator()
    batch = [_feat(role="button", name="A"), _feat(role="button", name="B")]
    r1, _ = alloc.assign(batch)
    r2, _ = alloc.assign(batch)
    assert r1 == r2 == ["e1", "e2"]


def test_refs_collide_disambiguation():
    """Two elements with identical features in the same batch get distinct refs."""
    alloc = RefAllocator()
    batch = [_feat(role="button", name="Edit"), _feat(role="button", name="Edit")]
    refs, fps = alloc.assign(batch)
    assert refs == ["e1", "e2"]
    assert fps[0] != fps[1]  # disambiguated


def test_refs_grow_monotonically_when_new_element_appears():
    alloc = RefAllocator()
    refs1, _ = alloc.assign([_feat(role="button", name="A")])
    assert refs1 == ["e1"]
    refs2, _ = alloc.assign([
        _feat(role="button", name="A"),
        _feat(role="button", name="B"),
    ])
    assert refs2[0] == "e1"  # A keeps its ref
    assert refs2[1] == "e2"  # B is new


def test_refs_never_recycle_after_removal():
    alloc = RefAllocator()
    refs1, _ = alloc.assign([_feat(role="button", name="A")])
    assert refs1 == ["e1"]
    # A disappears, only B present.
    refs2, _ = alloc.assign([_feat(role="button", name="B")])
    assert refs2 == ["e2"]
    # A reappears — gets a fresh ref, not e1, to avoid identity confusion.
    refs3, _ = alloc.assign([
        _feat(role="button", name="A"),
        _feat(role="button", name="B"),
    ])
    # B was last seen as e2, so it keeps e2; A is brand new again.
    assert refs3[1] == "e2"
    assert refs3[0] == "e3"


def test_refs_reset_after_goto():
    alloc = RefAllocator()
    alloc.assign([_feat(role="button", name="A")])
    alloc.reset()
    refs, _ = alloc.assign([_feat(role="button", name="A")])
    # Monotonic id continues, history forgotten — same content gets a new ref.
    assert refs == ["e2"]


# ----- State.find / find_all / to_prompt -----


def _state(*elements: Element) -> State:
    return State(
        elements=list(elements),
        context="https://example.com",
        captured_at=datetime.now(timezone.utc),
    )


def test_state_find_by_ref():
    s = _state(
        Element(ref="e1", role="button", name="OK", reachable=True),
        Element(ref="e2", role="textbox", name="Email", reachable=True),
    )
    assert s.find(ref="e2").role == "textbox"
    assert s.find(ref="e99") is None


def test_state_find_by_name_is_substring_case_insensitive():
    s = _state(
        Element(ref="e1", role="button", name="Sign In", reachable=True),
    )
    assert s.find(name="sign").ref == "e1"
    assert s.find(name="SIGN").ref == "e1"
    assert s.find(name="signup") is None


def test_state_find_excludes_unreachable_when_requested():
    s = _state(
        Element(ref="e1", role="button", name="OK", reachable=False),
        Element(ref="e2", role="button", name="OK", reachable=True),
    )
    assert s.find(name="OK", reachable=True).ref == "e2"


def test_to_prompt_default_omits_unreachable():
    s = _state(
        Element(ref="e1", role="button", name="OK", reachable=True),
        Element(ref="e2", role="button", name="Hidden", reachable=False),
    )
    out = s.to_prompt()
    assert "@e1" in out
    assert "@e2" not in out


def test_to_prompt_format():
    s = _state(
        Element(ref="e1", role="button", name="Sign In", reachable=True),
        Element(ref="e2", role="textbox", name="Email", reachable=True, value="user@x.com"),
    )
    out = s.to_prompt()
    assert '@e1 button "Sign In"' in out
    assert '@e2 textbox "Email" = "user@x.com"' in out


# ----- diff -----


def test_diff_added_removed_modified():
    prev = _state(
        Element(ref="e1", role="button", name="Open", reachable=True),
        Element(ref="e2", role="button", name="X",    reachable=True),
    )
    curr = _state(
        Element(ref="e1", role="button", name="Open", reachable=True),  # unchanged
        Element(ref="e3", role="dialog", name="Confirm?", reachable=True),  # added
        # e2 removed; e1 unchanged
    )
    d: DiffResult = curr.diff(prev)
    assert [e.ref for e in d.added] == ["e3"]
    assert [e.ref for e in d.removed] == ["e2"]
    assert d.modified == []
    assert d.unchanged_count == 1
    assert not d.empty


def test_diff_modified_when_reachable_flips():
    prev = _state(Element(ref="e1", role="button", name="Drawer", reachable=False))
    curr = _state(Element(ref="e1", role="button", name="Drawer", reachable=True))
    d = curr.diff(prev)
    assert len(d.modified) == 1
    assert d.modified[0][0].reachable is False
    assert d.modified[0][1].reachable is True


def test_diff_empty_when_identical():
    s = _state(Element(ref="e1", role="button", name="X", reachable=True))
    assert s.diff(s).empty


def test_diff_to_prompt_renders_added_removed_modified():
    prev = _state(
        Element(ref="e1", role="button", name="Open", reachable=True),
        Element(ref="e2", role="button", name="X",    reachable=True),
    )
    curr = _state(
        Element(ref="e1", role="button", name="Open", reachable=True),
        Element(ref="e3", role="dialog", name="Confirm?", reachable=True),
    )
    out = curr.diff(prev).to_prompt()
    assert "+@e3" in out
    assert "-@e2" in out
    assert "unchanged" in out
