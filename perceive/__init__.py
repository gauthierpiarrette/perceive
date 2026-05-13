"""perceive — compact, ref-stable, reachability-filtered perception for AI agents.

Example::

    import perceive

    with perceive.browser(url="https://example.com") as target:
        state = target.perceive()
        print(state.to_prompt())
        link = state.find(name="More information")
        if link:
            target.act("click", link.ref)

See SPEC.md for the full design rationale.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from perceive.browser import BrowserTarget
from perceive.errors import (
    ElementNotFoundError,
    PerceiveError,
    TargetClosedError,
    UnknownActionError,
)
from perceive.types import Bounds, DiffResult, Element, State

# Single source of truth: read the installed package's metadata so this string
# can never drift from pyproject.toml. Falls back to "0+local" when running
# from a source checkout without an installed dist-info.
try:
    __version__ = _pkg_version("perceive")
except PackageNotFoundError:
    __version__ = "0+local"

__all__ = [
    "__version__",
    # Factory
    "browser",
    # Types
    "BrowserTarget",
    "Bounds",
    "Element",
    "State",
    "DiffResult",
    # Errors
    "PerceiveError",
    "ElementNotFoundError",
    "TargetClosedError",
    "UnknownActionError",
]


def browser(
    url: str | None = None,
    *,
    headless: bool = True,
    viewport: tuple[int, int] = (1280, 800),
) -> BrowserTarget:
    """Open a browser target.

    Args:
        url: Optional URL to navigate to immediately. If omitted, the target
            starts on a blank page and you can call ``target.act("goto", url)``.
        headless: Whether to launch Chromium headless. Default True.
        viewport: ``(width, height)`` in CSS pixels.

    Returns:
        A :class:`BrowserTarget`. Caller is responsible for ``.close()`` or
        using it as a context manager.
    """
    return BrowserTarget(url=url, headless=headless, viewport=viewport)
