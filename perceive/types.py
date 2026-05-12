"""Public data types: Bounds, Element, State, DiffResult.

Design notes:
  * ``Element`` is frozen — once a State is returned to the caller, elements
    are immutable. This keeps diffing simple and avoids spooky-action-at-a-
    distance bugs.
  * ``State`` is mutable only in that it holds references to mutable adapter
    internals (the BrowserTarget keeps a handle map keyed by ref). The
    user-visible surface is read-only.
  * ``DiffResult.unchanged_count`` is a count, not a list — emitting every
    unchanged element to a prompt defeats the purpose of a diff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Optional


@dataclass(frozen=True)
class Bounds:
    """Bounding box in CSS pixels, relative to the viewport at capture time."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class Element:
    """A single perceived element."""

    ref: str
    role: str
    name: str
    reachable: bool
    bounds: Optional[Bounds] = None
    value: Optional[str] = None
    fingerprint: str = ""
    source: str = "a11y"          # "a11y" | "vision" — reserved for v0.3+
    confidence: float = 1.0        # 1.0 for a11y; <1.0 reserved for vision


@dataclass
class State:
    """The result of one ``target.perceive()`` call."""

    elements: list[Element]
    context: str                   # URL for browser, bundle_id for macos
    captured_at: datetime
    viewport: Optional[Bounds] = None
    text: Optional[str] = None     # populated when include_text=True
    tokens_estimate: int = 0       # of to_prompt() output

    def __iter__(self) -> Iterator[Element]:
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    def find(
        self,
        *,
        ref: Optional[str] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        reachable: Optional[bool] = None,
    ) -> Optional[Element]:
        """Return the first element matching all provided criteria, or None.

        ``name`` is a case-insensitive substring match. Other criteria are
        exact.
        """
        for el in self.elements:
            if ref is not None and el.ref != ref:
                continue
            if role is not None and el.role != role:
                continue
            if name is not None and name.lower() not in (el.name or "").lower():
                continue
            if reachable is not None and el.reachable != reachable:
                continue
            return el
        return None

    def find_all(
        self,
        *,
        role: Optional[str] = None,
        name: Optional[str] = None,
        reachable: Optional[bool] = None,
    ) -> list[Element]:
        out = []
        for el in self.elements:
            if role is not None and el.role != role:
                continue
            if name is not None and name.lower() not in (el.name or "").lower():
                continue
            if reachable is not None and el.reachable != reachable:
                continue
            out.append(el)
        return out

    def to_prompt(self, *, only_reachable: bool = True) -> str:
        """Compact rendering for inclusion in an LLM prompt.

        Format::

            @e1 button "Sign In"
            @e2 textbox "Email"
            @e3 textbox "Password"

        Unreachable elements are omitted by default — they exist on the State
        for inspection but should not be offered to the model as actionable.
        """
        from perceive._prompt import render_state
        return render_state(self, only_reachable=only_reachable)

    def diff(self, previous: "State") -> "DiffResult":
        """Diff this State against an earlier one from the same Target.

        Both states must come from the same Target (so refs are comparable).
        Returns ``added``, ``removed``, ``modified``, and ``unchanged_count``.
        """
        from perceive._diff import compute_diff
        return compute_diff(previous, self)


@dataclass
class DiffResult:
    """Result of ``State.diff(previous)``."""

    added: list[Element] = field(default_factory=list)
    removed: list[Element] = field(default_factory=list)
    modified: list[tuple[Element, Element]] = field(default_factory=list)
    unchanged_count: int = 0

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed and not self.modified

    def to_prompt(self) -> str:
        from perceive._prompt import render_diff
        return render_diff(self)


@dataclass
class Observation:
    """Yielded by ``target.observe_change()``. Populated on context-manager exit."""

    before: State
    after: Optional[State] = None
    diff: Optional[DiffResult] = None
