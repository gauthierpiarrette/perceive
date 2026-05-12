"""Exception hierarchy for perceive."""


class PerceiveError(Exception):
    """Base class for all perceive errors."""


class TargetClosedError(PerceiveError):
    """Raised when an operation is attempted on a closed target."""


class ElementNotFoundError(PerceiveError):
    """Raised when an action references a ref that is not in the current state.

    Most commonly this happens after a navigation: the previous state's refs
    are invalidated. Call ``target.perceive()`` again before acting.
    """


class StaleStateError(PerceiveError):
    """Raised when the underlying page context has changed (e.g. navigation)
    since the last perceive() call, invalidating internal handles."""


class UnknownActionError(PerceiveError):
    """Raised when ``target.act(action, ...)`` receives an unknown action name."""
