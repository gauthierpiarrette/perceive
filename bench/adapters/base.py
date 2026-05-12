"""Adapter base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bench.types import AdapterResult


class PerceptionAdapter(ABC):
    """Subclass and implement perceive() to register a new perception tool."""

    name: str = "unset"

    @abstractmethod
    def perceive(self, url: str) -> AdapterResult:
        """Open `url`, observe it, and return a structured snapshot."""
        ...
