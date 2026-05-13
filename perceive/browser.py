"""Browser target backed by Playwright Chromium (CDP).

A single Target owns one browser, one page, and one RefAllocator. The
RefAllocator carries refs across successive ``perceive()`` calls so that
``state.diff(previous)`` is meaningful and ``target.act("click", ref)``
keeps working through DOM mutations.

Acting:
  * ``click`` and ``type`` go through Playwright's input layer (real mouse
    moves and keyboard events — trusted events). Coordinates are recomputed
    fresh against the page after a scrollIntoView, so a stale State that
    scrolled or animated does not produce a missed click.
  * ``scroll``, ``press``, ``goto``, and ``wait`` are global and do not
    require a ref.

Lifecycle:
  * Construct with optional ``url=``. The browser stays alive until
    ``close()`` (or context-manager exit).
  * ``goto()`` resets the RefAllocator because the entire page identity is
    new.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Iterator, Optional

from perceive._js import COLLECT_JS, ELEMENT_BOUNDS_JS, SET_VALUE_JS
from perceive._refs import Features, RefAllocator
from perceive.errors import (
    ElementNotFoundError,
    TargetClosedError,
    UnknownActionError,
)
from perceive.types import Bounds, Element, Observation, State


class BrowserTarget:
    """A live Chromium page that can be perceived and acted on."""

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        headless: bool = True,
        viewport: tuple[int, int] = (1280, 800),
    ) -> None:
        from playwright.sync_api import sync_playwright  # lazy import

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._page = self._browser.new_page(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        self._refs = RefAllocator()
        # Handle ids are short-lived: a fresh map is built every perceive() call,
        # so an action targeting a stale ref fails cleanly.
        self._handles: dict[str, str] = {}  # ref → handle_id
        self._closed = False

        if url:
            self.goto(url)

    # ----- lifecycle -----

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._pw.stop()

    def __enter__(self) -> "BrowserTarget":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        # Defensive — close() is idempotent. Don't rely on this; it can fire
        # at interpreter shutdown when Playwright internals are already gone.
        with contextlib.suppress(Exception):
            self.close()

    # ----- core ops -----

    def goto(self, url: str, *, wait_until: str = "load") -> None:
        self._ensure_open()
        self._page.goto(url, wait_until=wait_until)
        # A new page is a new universe — drop ref history.
        self._refs.reset()
        self._handles.clear()

    def perceive(
        self,
        *,
        region: Optional[tuple[float, float, float, float] | str] = None,
        role: Optional[str] = None,
        include_text: bool = False,
        include_unreachable: bool = False,
    ) -> State:
        """Return a structured snapshot of the current page state.

        Args:
            region: A CSS selector or ``(x, y, w, h)`` viewport-bbox to scope
                the capture. Reduces the token cost on large pages.
            role: Filter elements to a single role (e.g. ``"button"``).
            include_text: Reserved for future text-content capture. v0.1 just
                exposes the flag so callers can opt-in once supported.
            include_unreachable: When True, unreachable elements are returned
                with ``reachable=False`` instead of being filtered out.
        """
        self._ensure_open()
        opts = {
            "regionSelector": region if isinstance(region, str) else None,
            "regionBBox": list(region) if isinstance(region, tuple) else None,
            "role": role,
            "includeUnreachable": include_unreachable,
        }
        raw = self._page.evaluate(COLLECT_JS, opts)

        features_batch = [_features_from_raw(r) for r in raw["elements"]]
        refs, fingerprints = self._refs.assign(features_batch)

        self._handles = {refs[i]: r["handle_id"] for i, r in enumerate(raw["elements"])}

        elements = [
            Element(
                ref=refs[i],
                role=r["role"],
                name=r["name"],
                value=(r.get("value") or None),
                reachable=bool(r["reachable"]),
                bounds=Bounds(*r["bbox"]) if r.get("bbox") else None,
                unreachable_reason=r.get("unreachable_reason"),
                fingerprint=fingerprints[i],
            )
            for i, r in enumerate(raw["elements"])
        ]

        vw, vh = raw["viewport"][2], raw["viewport"][3]
        state = State(
            elements=elements,
            context=raw["url"],
            captured_at=datetime.now(timezone.utc),
            viewport=Bounds(0, 0, vw, vh),
            text=None,  # include_text reserved for v0.2
        )
        state.tokens_estimate = _estimate_tokens(state)
        return state

    def act(self, action: str, ref: Optional[str] = None, *args, **kwargs) -> None:
        """Perform an action.

        Supported actions::

            act("click", ref)
            act("type", ref, text)              # or text=...
            act("set_value", ref, text)         # programmatic, for tricky inputs
            act("scroll", direction="down", amount=400)
            act("press", key)                   # or key=...
            act("goto", url)                    # or url=...
            act("wait", seconds)                # or seconds=...
        """
        self._ensure_open()
        if action == "click":
            self._click(self._require_ref(ref, action))
        elif action == "type":
            text = kwargs.get("text", args[0] if args else "")
            self._type(self._require_ref(ref, action), text)
        elif action == "set_value":
            text = kwargs.get("text", args[0] if args else "")
            self._set_value(self._require_ref(ref, action), text)
        elif action == "scroll":
            self._scroll(
                direction=kwargs.get("direction", "down"),
                amount=kwargs.get("amount", 400),
            )
        elif action == "press":
            key = kwargs.get("key", ref if ref else (args[0] if args else ""))
            if not key:
                raise UnknownActionError("act('press', key) requires a key name")
            self._page.keyboard.press(key)
        elif action == "goto":
            url = kwargs.get("url", ref if ref else (args[0] if args else ""))
            if not url:
                raise UnknownActionError("act('goto', url) requires a url")
            self.goto(url)
        elif action == "wait":
            seconds = kwargs.get("seconds", float(ref) if ref else (args[0] if args else 1.0))
            self._page.wait_for_timeout(int(float(seconds) * 1000))
        else:
            raise UnknownActionError(f"Unknown action: {action!r}")

    @contextlib.contextmanager
    def observe_change(self, *, settle_ms: int = 200) -> Iterator[Observation]:
        """Capture before/after states around a block, exposing the diff.

        >>> with target.observe_change() as obs:
        ...     target.act("click", "e1")
        >>> obs.diff.to_prompt()
        """
        before = self.perceive()
        obs = Observation(before=before)
        try:
            yield obs
        finally:
            self._page.wait_for_timeout(settle_ms)
            after = self.perceive()
            obs.after = after
            obs.diff = after.diff(before)

    # ----- internals -----

    def _ensure_open(self) -> None:
        if self._closed:
            raise TargetClosedError("Target has been closed")

    def _require_ref(self, ref: Optional[str], action: str) -> str:
        if ref is None:
            raise UnknownActionError(f"act({action!r}, ref, …) requires a ref")
        if ref not in self._handles:
            raise ElementNotFoundError(
                f"ref {ref!r} not in current perception state — re-perceive after navigation"
            )
        return ref

    def _fresh_bounds(self, ref: str) -> Bounds:
        handle_id = self._handles[ref]
        result = self._page.evaluate(ELEMENT_BOUNDS_JS, {"handle_id": handle_id})
        if not result:
            raise ElementNotFoundError(f"ref {ref!r} no longer in DOM")
        return Bounds(*result)

    def _click(self, ref: str) -> None:
        b = self._fresh_bounds(ref)
        self._page.mouse.click(b.cx, b.cy)

    def _type(self, ref: str, text: str) -> None:
        b = self._fresh_bounds(ref)
        self._page.mouse.click(b.cx, b.cy)
        # Use keyboard.type to fire real key events (trusted) rather than
        # blasting el.value, so site-side validation runs.
        if text:
            self._page.keyboard.type(text)

    def _set_value(self, ref: str, text: str) -> None:
        ok = self._page.evaluate(
            SET_VALUE_JS,
            {"handle_id": self._handles[ref], "text": text},
        )
        if not ok:
            raise ElementNotFoundError(f"ref {ref!r}: element no longer supports value-set")

    def _scroll(self, *, direction: str, amount: int) -> None:
        dy = amount if direction == "down" else -amount if direction == "up" else 0
        dx = amount if direction == "right" else -amount if direction == "left" else 0
        if dx == 0 and dy == 0:
            raise UnknownActionError(f"act('scroll'): direction must be up|down|left|right")
        self._page.mouse.wheel(dx, dy)


# ----- module helpers -----


def _features_from_raw(r: dict) -> Features:
    return Features(
        role=r.get("role") or "",
        name=r.get("name") or "",
        aria_label=r.get("aria_label") or "",
        test_id=r.get("test_id") or "",
        id_attr=r.get("id_attr") or "",
        name_attr=r.get("name_attr") or "",
        href=r.get("href") or "",
        parent_landmark=r.get("parent_landmark") or "",
        row_context=r.get("row_context") or "",
    )


def _estimate_tokens(state: State) -> int:
    """Rough token estimate for the compact prompt — 1 token per 4 chars."""
    text = state.to_prompt()
    return max(1, len(text) // 4)
