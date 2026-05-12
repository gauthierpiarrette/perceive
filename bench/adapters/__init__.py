"""Adapter registry. Add new adapters here so the CLI can find them."""

from __future__ import annotations

from typing import Callable

from bench.adapters.base import PerceptionAdapter


def _lazy(loader: Callable[[], type[PerceptionAdapter]]):
    """Defer importing playwright until the adapter is actually used."""
    return loader


def _playwright_baseline_loader():
    from bench.adapters.playwright_baseline import PlaywrightBaselineAdapter
    return PlaywrightBaselineAdapter


def _playwright_filtered_loader():
    from bench.adapters.playwright_filtered import PlaywrightFilteredAdapter
    return PlaywrightFilteredAdapter


def _perceive_loader():
    from bench.adapters.perceive_adapter import PerceiveAdapter
    return PerceiveAdapter


REGISTRY: dict[str, Callable[[], type[PerceptionAdapter]]] = {
    "playwright_baseline": _lazy(_playwright_baseline_loader),
    "playwright_filtered": _lazy(_playwright_filtered_loader),
    "perceive": _lazy(_perceive_loader),
}


def get_adapter(name: str) -> PerceptionAdapter:
    if name not in REGISTRY:
        available = ", ".join(REGISTRY.keys())
        raise KeyError(f"Unknown adapter '{name}'. Available: {available}")
    return REGISTRY[name]()()


def list_adapters() -> list[str]:
    return sorted(REGISTRY.keys())
