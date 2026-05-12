"""Match adapter elements to ground-truth elements.

The runner fetches each ground-truth element's actual bbox from the page (via
Playwright) and stores it on GroundTruthElement.bbox. This file then matches by
bbox proximity + role/name similarity.
"""

from __future__ import annotations

from bench.types import GroundTruthElement, Match, PerceivedElement

_ROLE_ALIASES = {
    # Map a few synonyms we encounter so role mismatches don't kill matches.
    "link": ["link", "a"],
    "button": ["button"],
    "textbox": ["textbox", "input", "textarea"],
    "img": ["img", "image"],
}


def _role_eq(a: str, b: str) -> bool:
    a = (a or "").lower()
    b = (b or "").lower()
    if a == b:
        return True
    for canonical, aliases in _ROLE_ALIASES.items():
        if a in aliases and b in aliases:
            return True
    return False


def _name_similarity(a: str, b: str) -> float:
    """Cheap normalized-substring overlap. 1.0 = exact, 0.0 = nothing."""
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return shorter / longer
    # Token-set Jaccard.
    ta, tb = set(a.split()), set(b.split())
    inter = ta & tb
    union = ta | tb
    if not union:
        return 0.0
    return len(inter) / len(union)


def _bbox_iou(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _bbox_center_distance(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acx, acy = ax + aw / 2, ay + ah / 2
    bcx, bcy = bx + bw / 2, by + bh / 2
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def match_score(bench: GroundTruthElement, adapter_el: PerceivedElement) -> float:
    """Return 0..1 similarity between a ground-truth element and an adapter element."""
    role_score = 1.0 if _role_eq(bench.role, adapter_el.role) else 0.3
    name_score = _name_similarity(bench.name, adapter_el.name)
    if bench.bbox is not None and adapter_el.bbox is not None:
        iou = _bbox_iou(bench.bbox, adapter_el.bbox)
        # Strong signal if IoU is decent.
        bbox_score = max(iou, 0.0)
        # If IoU is zero (different elements), also check center distance falls within 10px;
        # this handles adapters that emit slightly-larger bounding boxes than the element.
        if bbox_score < 0.1:
            d = _bbox_center_distance(bench.bbox, adapter_el.bbox)
            if d < 10:
                bbox_score = 0.5
    else:
        bbox_score = 0.0

    # Weighted sum. If we have bbox, it dominates. Otherwise role+name carry it.
    if bench.bbox is not None and adapter_el.bbox is not None:
        return 0.6 * bbox_score + 0.2 * role_score + 0.2 * name_score
    return 0.5 * name_score + 0.5 * role_score


def match_elements(
    bench_elements: list[GroundTruthElement],
    adapter_elements: list[PerceivedElement],
    threshold: float = 0.35,
) -> list[Match]:
    """Greedy 1:1 matching from ground-truth to adapter elements.

    Each ground-truth element gets the highest-scoring still-available adapter
    element above the threshold, otherwise None.
    """
    matches: list[Match] = []
    used: set[int] = set()

    # Score all pairs first so we can do best-first assignment.
    scored: list[tuple[float, int, int]] = []
    for bi, b in enumerate(bench_elements):
        for ai, a in enumerate(adapter_elements):
            s = match_score(b, a)
            if s >= threshold:
                scored.append((s, bi, ai))
    scored.sort(reverse=True)

    bench_to_adapter: dict[int, tuple[int, float]] = {}
    for s, bi, ai in scored:
        if bi in bench_to_adapter or ai in used:
            continue
        bench_to_adapter[bi] = (ai, s)
        used.add(ai)

    for bi, b in enumerate(bench_elements):
        if bi in bench_to_adapter:
            ai, s = bench_to_adapter[bi]
            matches.append(Match(bench=b, adapter=adapter_elements[ai], score=s))
        else:
            matches.append(Match(bench=b, adapter=None, score=0.0))
    return matches
