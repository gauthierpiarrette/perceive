# Contributing to perceive

Thanks for considering a contribution. `perceive` is small on purpose.

## Quick start

```bash
git clone https://github.com/gauthierpiarrette/perceive
cd perceive
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m playwright install chromium
```

## Running the tests

```bash
pytest tests/                                                  # all 33 tests
pytest tests/test_perceive_unit.py                             # unit only (fast, no browser)
pytest tests/test_perceive_e2e.py                              # end-to-end (requires Chromium)
pytest tests/test_smoke.py                                     # bench-infrastructure smoke tests
```

CI runs all three on every PR (`.github/workflows/test.yml`) across Python 3.10–3.12 on Ubuntu. Please make sure the suite is green locally before opening a PR.

## Running the benchmark

```bash
perceive-bench list pages                                                # 14 conformance pages
perceive-bench list adapters                                             # 3 adapters: baseline / filtered / perceive

perceive-bench run --adapter perceive --suite reachability               # must report P=R=F1=1.0
perceive-bench run --adapter perceive --suite tokens
perceive-bench run --adapter perceive --suite determinism --runs 5
```

Results land in `results/*.json`. CI fails any change that drops reachability below 1.000 — that's intentional.

## Adding a new conformance page

The benchmark is the load-bearing artifact of this project. The fastest way to make `perceive` stronger is to add a hard page.

1. Create `bench/pages/<NN>_<description>.html`. Use one of the existing pages as a template.
2. Each page **must** include a `<script type="application/json" id="ground-truth">` block. Every interactable element gets a `data-bench-id="..."` attribute; the ground-truth block lists the same `bench_id`s with their expected `role`, `name`, and `reachable` value (plus an optional `reason` string for unreachable cases).
3. Add the page to `bench/pages/manifest.json`.
4. Run `perceive-bench run --adapter perceive --suite reachability` to see how `perceive` scores against your new page.
5. If `perceive` misses, that's a useful bug — the page exercises something the reachability algorithm doesn't handle. Open an issue or fix the algorithm in `perceive/_js.py`.

Patterns we still want pages for (see SPEC §8.1): virtualized lists, portals, nested modals, cookie banners, real component-library frameworks (Radix, MUI, Ant Design, Headless UI), animated layout shift, table rows with repeated actions.

## Adding a new adapter

Adapters let the bench measure perception tools other than `perceive` itself — e.g. Playwright MCP, Vercel agent-browser, Chrome DevTools MCP. The framework is designed for this.

1. Create `bench/adapters/<your_adapter>.py` subclassing `PerceptionAdapter` and implementing `perceive(url: str) -> AdapterResult`. See `bench/adapters/playwright_baseline.py` for the simplest reference.
2. Register the adapter in `bench/adapters/__init__.py`.
3. `perceive-bench list adapters` should now show your adapter; `perceive-bench run --adapter <name> --suite reachability` runs it against the conformance suite.

## Code style

- Python ≥ 3.10. We use the `str | None` union syntax.
- Type-annotate every public function. Internal helpers should be annotated too, but not strictly required.
- Dataclasses for value types (`Element`, `State`, `Bounds`, `DiffResult` are all `@dataclass`).
- No formatter enforced. Match the file you're editing; existing code is roughly Black-compatible with 100-char lines.
- Imports: stdlib, third-party, then local. `from __future__ import annotations` is fine to add when needed.

## Commits and PRs

- One logical change per PR. A new conformance page is one PR; an algorithm change is another.
- A PR that changes `perceive/_js.py` must keep `perceive-bench run --adapter perceive --suite reachability` at 1.000.
- Reference any open issue (`Closes #123`).
- No need to update `CHANGELOG.md` in feature PRs — we batch it at release time.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
