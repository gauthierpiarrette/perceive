"""State diffing.

Two states from the same Target share a ref namespace (the Target's
RefAllocator carries refs forward across perceives). That makes diff a pure
set/membership operation over refs, with field comparison for ``modified``.

This is intentionally simpler than diffing by fingerprint or by DOM
position: the heavy lifting is in the RefAllocator. Diff is just a view
over what it produced.
"""

from __future__ import annotations

from perceive.types import DiffResult, State


def compute_diff(previous: State, current: State) -> DiffResult:
    prev_by_ref = {e.ref: e for e in previous.elements}
    curr_by_ref = {e.ref: e for e in current.elements}

    added = [e for e in current.elements if e.ref not in prev_by_ref]
    removed = [e for e in previous.elements if e.ref not in curr_by_ref]

    modified: list[tuple] = []
    unchanged = 0
    for ref, curr in curr_by_ref.items():
        prev = prev_by_ref.get(ref)
        if prev is None:
            continue  # already counted in `added`
        if (
            prev.name != curr.name
            or prev.value != curr.value
            or prev.reachable != curr.reachable
        ):
            modified.append((prev, curr))
        else:
            unchanged += 1

    return DiffResult(
        added=added,
        removed=removed,
        modified=modified,
        unchanged_count=unchanged,
    )
