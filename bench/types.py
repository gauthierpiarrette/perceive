"""Data types shared across adapters, runner, and metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PerceivedElement:
    """An element returned by a perception adapter."""

    role: str
    name: str
    reachable: bool
    bbox: Optional[tuple[float, float, float, float]] = None  # x, y, w, h in CSS pixels
    # Optional context an adapter may surface — not required, but useful for matching.
    extra: dict = field(default_factory=dict)


@dataclass
class AdapterResult:
    """Result of one perceive() call from an adapter."""

    adapter_name: str
    url: str
    elements: list[PerceivedElement]
    raw_payload: str  # what would be sent to the LLM; used for token counting
    captured_at: datetime
    latency_ms: float
    notes: dict = field(default_factory=dict)


@dataclass
class GroundTruthElement:
    bench_id: str
    role: str
    name: str
    reachable: bool
    reason: Optional[str] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    in_shadow_dom: bool = False
    in_iframe: bool = False


@dataclass
class GroundTruth:
    page_id: str
    category: str
    description: str
    elements: list[GroundTruthElement]


@dataclass
class Match:
    """A pairing of a ground-truth element with the adapter element that matches it (or None)."""

    bench: GroundTruthElement
    adapter: Optional[PerceivedElement]
    score: float  # 0..1, similarity that produced the match
