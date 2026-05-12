"""Metrics computed from matched adapter results vs ground truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from bench.types import AdapterResult, Match


@dataclass
class ReachabilityMetrics:
    page_id: str
    adapter_name: str
    # Reachability classification (treating "reachable" as the positive class).
    true_positive: int   # adapter says reachable, ground truth says reachable
    false_positive: int  # adapter says reachable, ground truth says NOT reachable  (the costly error: agent will try unreachable elements)
    true_negative: int   # adapter says NOT reachable, ground truth says NOT reachable
    false_negative: int  # adapter says NOT reachable, ground truth says reachable
    missed: int          # ground truth element not present in adapter output at all
    extra: int           # adapter element with no matching ground truth (informational)
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict:
        return asdict(self)


def reachability(
    matches: list[Match],
    adapter_extras: int,
    page_id: str,
    adapter_name: str,
) -> ReachabilityMetrics:
    tp = fp = tn = fn = missed = 0
    for m in matches:
        if m.adapter is None:
            missed += 1
            # Treat misses as worst case for whichever class:
            # if it was reachable, that's a false negative (agent will not act).
            # if it was unreachable, that's effectively a true negative (we won't try).
            if m.bench.reachable:
                fn += 1
            else:
                tn += 1
            continue
        bench_r = m.bench.reachable
        adapter_r = m.adapter.reachable
        if bench_r and adapter_r:
            tp += 1
        elif not bench_r and adapter_r:
            fp += 1  # the costly error
        elif not bench_r and not adapter_r:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return ReachabilityMetrics(
        page_id=page_id,
        adapter_name=adapter_name,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        missed=missed,
        extra=adapter_extras,
        precision=precision,
        recall=recall,
        f1=f1,
    )


# ---------- Token cost ----------


_ENC = None


def _get_encoding():
    global _ENC
    if _ENC is None:
        import tiktoken  # imported lazily so it's not required to print page list
        try:
            _ENC = tiktoken.get_encoding("o200k_base")  # newer (GPT-4o family)
        except Exception:
            _ENC = tiktoken.get_encoding("cl100k_base")
    return _ENC


def token_count(text: str) -> int:
    """Token count of a string under a modern tokenizer (o200k_base if available)."""
    return len(_get_encoding().encode(text))


# ---------- Determinism ----------


def determinism_exact_match(results: list[AdapterResult]) -> float:
    """Fraction of (role, name, reachable) sets that exactly match the first result.

    Returns 1.0 if all runs are identical. Returns 0.0 if no runs match the first.
    """
    if len(results) < 2:
        return 1.0
    baseline = _signature(results[0])
    matches = sum(1 for r in results[1:] if _signature(r) == baseline)
    return matches / (len(results) - 1)


def _signature(result: AdapterResult) -> tuple:
    return tuple(sorted((e.role, e.name, e.reachable) for e in result.elements))
