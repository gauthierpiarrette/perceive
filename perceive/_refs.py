"""Stable-ref allocation across successive ``perceive()`` calls.

Algorithm (per SPEC §7.4, simplified for v0.1):

1. Each element has a *fingerprint* derived from features that are stable
   across reflows: role, accessible name, ARIA label, stable attributes
   (``data-testid``, ``id``, ``name``), nearest landmark ancestor, and a
   role-only signature of immediate siblings.
2. Within one ``perceive()`` call, fingerprint collisions are disambiguated
   by appending the element's DOM-order index (1, 2, …) to the fingerprint.
   This handles repeated identical buttons (e.g. "Edit" in many table rows).
3. Across calls, an element's ref is preserved iff its disambiguated
   fingerprint matches an element from the previous call.
4. Otherwise a new ref ``eN`` is allocated.

The scored-similarity fallback for unmatched elements described in the spec
is not yet implemented. Whether it is necessary is decided by the
``determinism`` benchmark — if exact-fingerprint matching achieves the
target there, we ship without it.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Features:
    """The raw features collected from one element. Used to compute fingerprints."""

    role: str
    name: str
    aria_label: str
    test_id: str           # data-testid / data-test / data-qa, first that's present
    id_attr: str
    name_attr: str         # form-element name attribute
    href: str              # links only
    parent_landmark: str   # role of nearest landmark ancestor ('', if none)
    sibling_signature: str # joined roles of immediate siblings, sorted

    def fingerprint(self) -> str:
        """Stable hash from identity features only — no positional info."""
        # Each part is separated by NUL so that no separator collision is possible.
        parts = "\0".join([
            self.role,
            self.name,
            self.aria_label,
            self.test_id,
            self.id_attr,
            self.name_attr,
            self.href,
            self.parent_landmark,
            self.sibling_signature,
        ])
        return hashlib.sha1(parts.encode("utf-8")).hexdigest()[:12]


class RefAllocator:
    """Assigns stable refs (``e1``, ``e2``, …) across successive perceive() calls."""

    def __init__(self) -> None:
        self._next_id = 1
        # Map of disambiguated fingerprint → ref from the previous call.
        self._prev: dict[str, str] = {}

    def assign(self, features_batch: list[Features]) -> tuple[list[str], list[str]]:
        """Assign refs to a new batch of features.

        Returns:
            (refs, fingerprints) parallel to ``features_batch``.
            ``fingerprints`` are the disambiguated fingerprints, exposed on the
            Element for debugging and downstream tooling.
        """
        # Compute base fingerprints.
        base = [f.fingerprint() for f in features_batch]
        # Disambiguate duplicates within this batch by appending the count.
        seen: Counter[str] = Counter()
        disambiguated: list[str] = []
        for fp in base:
            seen[fp] += 1
            if seen[fp] == 1:
                disambiguated.append(fp)
            else:
                disambiguated.append(f"{fp}#{seen[fp]}")

        # Assign refs: prior match wins; otherwise allocate a fresh id.
        refs: list[str] = []
        new_map: dict[str, str] = {}
        for fp in disambiguated:
            ref = self._prev.get(fp)
            if ref is None:
                ref = f"e{self._next_id}"
                self._next_id += 1
            refs.append(ref)
            new_map[fp] = ref

        self._prev = new_map
        return refs, disambiguated

    def reset(self) -> None:
        """Forget all prior refs. Called on navigation."""
        self._prev = {}
        # Note: _next_id is intentionally NOT reset, so refs are monotonic
        # across the entire target session and never reused.
