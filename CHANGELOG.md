# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-05-13

### Fixed
- Reachability algorithm: a `position:fixed` ancestor (e.g. a slide-in drawer) now correctly propagates its escape from ancestor `overflow:hidden` clipping to its static descendants. Previously, content inside a fixed-positioned drawer was wrongly flagged unreachable when the body had `overflow-x:hidden`, even after the drawer opened. Algorithm change in `perceive/_js.py`; bench remains at P=R=F1=1.000.

## [0.1.0] — 2026-05-13

First public release. Browser-only; macOS / Windows / Linux backends and a vision fallback are on the roadmap (see README).

### Added

- `perceive.browser(url=..., headless=True, viewport=(1280, 800))` — a Playwright-backed browser target.
- `target.perceive(region=, role=, include_unreachable=)` — compact, ref-stable, reachability-filtered snapshot of the page.
- `target.act(action, ref=, ...)` — `click`, `type`, `set_value`, `scroll`, `press`, `goto`, `wait`. Clicks and types go through Playwright's input layer (trusted events).
- `target.observe_change(settle_ms=200)` — context manager that captures a before/after diff around an action.
- `state.find(...)`, `state.find_all(...)`, `state.to_prompt(only_reachable=True)`, `state.diff(previous)`.
- Reachability filtering at the library level: handles `display:none`, `visibility:hidden`, `opacity:0`, `pointer-events:none`, off-screen transforms, parent overflow clipping, modal occlusion, sticky-header overlap, `inert`/`aria-hidden` ancestors, disabled controls, open Shadow DOM traversal, same-origin iframes. Algorithm and rationale: SPEC §7.3, validated against the 14-page conformance suite.
- Stable refs across `perceive()` calls via a 9-feature fingerprint with within-batch disambiguation for repeated identical elements.
- 14-page reachability conformance suite in `bench/` plus three measurement suites (`reachability`, `tokens`, `determinism`) and a `perceive-bench` CLI.

### Benchmark results at release

Measured on the 14-page conformance suite. The baseline models the failure pattern documented in [Playwright #39955](https://github.com/microsoft/playwright/issues/39955).

| Adapter | Precision | Recall | F1 | False positives | Median `to_prompt()` tokens / page |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline (no reachability filtering) | 0.528 | 1.000 | 0.691 | 17 / 36 | 21.5 |
| **`perceive`** | **1.000** | **1.000** | **1.000** | **0 / 36** | **8.0** |

Determinism: 1.000 mean exact-match rate across 14 pages × 5 runs each.

[0.1.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauthierpiarrette/perceive/releases/tag/v0.1.0
