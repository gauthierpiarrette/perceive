"""CLI entry point for perceive-bench."""

from __future__ import annotations

import argparse
import sys

from bench.adapters import list_adapters
from bench.manifest import list_page_ids, load_manifest
from bench.runner import (
    resolve_page_ids,
    run_determinism,
    run_reachability,
    run_tokens,
    write_results_json,
)


def _cmd_list(args: argparse.Namespace) -> int:
    if args.what == "pages":
        manifest = load_manifest()
        print(f"{len(manifest['pages'])} pages:\n")
        for p in manifest["pages"]:
            print(f"  {p['id']:<32} [{p['category']}]")
    elif args.what == "adapters":
        adapters = list_adapters()
        print(f"{len(adapters)} adapters:\n")
        for a in adapters:
            print(f"  {a}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    page_ids = resolve_page_ids(args.pages)
    print(f"adapter={args.adapter}  suite={args.suite}  pages={len(page_ids)}", file=sys.stderr)

    if args.suite == "reachability":
        result = run_reachability(args.adapter, page_ids)
        _print_reachability(result)
    elif args.suite == "tokens":
        result = run_tokens(args.adapter, page_ids)
        _print_tokens(result)
    elif args.suite == "determinism":
        result = run_determinism(args.adapter, page_ids, runs=args.runs)
        _print_determinism(result)
    else:
        print(f"Unknown suite: {args.suite}", file=sys.stderr)
        return 2

    path = write_results_json(f"{args.suite}_{args.adapter}", result)
    print(f"\nWrote {path}", file=sys.stderr)
    return 0


# --- pretty printers ---------------------------------------------------------


def _print_reachability(result: dict) -> None:
    summary = result["summary"]
    print()
    print(f"== Reachability — {result['adapter']} ==")
    print(f"  pages       : {summary['n_pages']}")
    print(f"  precision   : {summary['precision']:.3f}    (1.0 = no false positives)")
    print(f"  recall      : {summary['recall']:.3f}    (1.0 = found every reachable element)")
    print(f"  F1          : {summary['f1']:.3f}")
    print(f"  TP / FP / TN / FN / missed : "
          f"{summary['true_positive']} / {summary['false_positive']} / "
          f"{summary['true_negative']} / {summary['false_negative']} / {summary['missed']}")
    print()
    print(f"{'page':<32}{'P':>6}{'R':>6}{'F1':>7}{'FP':>5}{'FN':>5}")
    for p in result["pages"]:
        m = p["metrics"]
        print(f"  {p['page_id']:<30}{m['precision']:>6.2f}{m['recall']:>6.2f}{m['f1']:>7.2f}{m['false_positive']:>5}{m['false_negative']:>5}")


def _print_tokens(result: dict) -> None:
    summary = result["summary"]
    print()
    print(f"== Tokens — {result['adapter']} ==")
    print(f"  median tokens  : {summary['median_tokens']}")
    print(f"  p95 tokens     : {summary['p95_tokens']}")
    print(f"  median latency : {summary['median_latency_ms']:.1f} ms")
    print()
    print(f"{'page':<32}{'elements':>10}{'lines':>8}{'tokens':>9}{'latency_ms':>14}")
    for p in result["pages"]:
        print(f"  {p['page_id']:<30}{p['elements_emitted']:>10}{p['elements_in_payload']:>8}{p['tokens']:>9}{p['latency_ms']:>14.1f}")


def _print_determinism(result: dict) -> None:
    summary = result["summary"]
    print()
    print(f"== Determinism — {result['adapter']} ==")
    print(f"  mean exact-match rate : {summary['mean_exact_match_rate']:.3f}")
    print()
    print(f"{'page':<32}{'runs':>6}{'exact_match':>14}{'counts':>20}")
    for p in result["pages"]:
        counts = "/".join(str(c) for c in p["element_counts"])
        print(f"  {p['page_id']:<30}{p['runs']:>6}{p['exact_match_rate']:>14.2f}  {counts}")


# --- argparse ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="perceive-bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List available pages or adapters")
    p_list.add_argument("what", choices=["pages", "adapters"], default="pages", nargs="?")
    p_list.set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="Run a suite against an adapter")
    p_run.add_argument("--adapter", required=True, help="Adapter name (see `perceive-bench list adapters`)")
    p_run.add_argument(
        "--suite",
        required=True,
        choices=["reachability", "tokens", "determinism"],
        help="Which benchmark suite to run",
    )
    p_run.add_argument(
        "--pages",
        default="all",
        help="'all' (default), a comma-separated list, or a single page id",
    )
    p_run.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Runs per page (determinism suite only)",
    )
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
