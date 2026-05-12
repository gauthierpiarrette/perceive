"""Compact prompt rendering for ``State`` and ``DiffResult``.

The format is deliberately tiny and parseable by an LLM with no instruction.
A typical line is ~6–12 tokens. Quoted names are escaped only minimally —
embedded double-quotes are replaced with ``\\"``.
"""

from __future__ import annotations

from perceive.types import DiffResult, Element, State


def _line(prefix: str, el: Element) -> str:
    role = el.role or "element"
    name = (el.name or "").replace('"', '\\"')
    if el.value:
        # Show current text content for inputs.
        value = el.value.replace('"', '\\"')
        return f'{prefix}@{el.ref} {role} "{name}" = "{value}"'
    if name:
        return f'{prefix}@{el.ref} {role} "{name}"'
    return f"{prefix}@{el.ref} {role}"


def render_state(state: State, *, only_reachable: bool = True) -> str:
    lines = [
        _line("", el)
        for el in state.elements
        if not only_reachable or el.reachable
    ]
    return "\n".join(lines)


def render_diff(diff: DiffResult) -> str:
    lines: list[str] = []
    for el in diff.added:
        lines.append(_line("+", el))
    for el in diff.removed:
        lines.append(_line("-", el))
    for prev, curr in diff.modified:
        # Show transition succinctly.
        if prev.reachable != curr.reachable:
            mark = "*" if curr.reachable else "."
            lines.append(_line(mark, curr))
        else:
            lines.append(_line("*", curr))
    if diff.unchanged_count:
        lines.append(f"… {diff.unchanged_count} unchanged")
    return "\n".join(lines)
