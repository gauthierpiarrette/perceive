# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] — 2026-05-13

### Fixed
- Docstring and README comments around `include_text=True` no longer claim it is "reserved for v0.2" — v0.2.0 shipped without it. The flag is still accepted (for forward-compat) but unimplemented; the wording now says "reserved; not yet implemented" so the public surface matches runtime behavior. Pure documentation change; no code paths affected.

## [0.2.0] — 2026-05-13

### Added
- **`Element.unreachable_reason`** — a stable, snake_case slug naming the specific reason an unreachable element was filtered, or `None` for reachable elements. Values: `not_in_document`, `display_none`, `visibility_hidden`, `opacity_zero`, `css_hidden`, `zero_bounds`, `disabled`, `inert`, `aria_hidden`, `pointer_events_none`, `clipped_by_ancestor`, `offscreen`, `occluded`. Non-breaking API addition. Pulled forward from v0.2 after three rounds of external feedback consistently identified it as the biggest debuggability gap.

### Tests
- `test_unreachable_reason_is_specific` — parametrized across 10 cases that exercise every reason slug against the existing conformance pages.
- `test_reachable_elements_have_no_unreachable_reason` — pins the invariant that reachable elements carry `unreachable_reason == None`.
- `test_deleting_row_does_not_churn_other_rows_refs` — adversarial regression symmetric to the v0.1.3 row-insertion test; deleting a middle row leaves the other rows' Edit-button refs intact.
- `test_label_change_reissues_ref_known_limitation` — **pins** the documented v0.1 limitation that exact-fingerprint matching reissues the ref when an element's accessible name changes mid-session (e.g. "Save" → "Saving…"). Will be inverted when scored-similarity matching ships in v0.3.

## [0.1.3] — 2026-05-13

### Fixed
- **Ref stability under sibling mutation.** Adding or removing a sibling element no longer churns the refs of unrelated elements. The fingerprint feature `sibling_signature` (joined sibling role names) has been removed — its only effect was breaking ref stability whenever any sibling was added, while contributing no actual disambiguation value.
- **Ref stability under row insertion/reordering.** Inserting a new row above existing ones no longer slides every subsequent Edit-button ref to the wrong element. A new fingerprint feature `row_context` captures the text of the nearest row / list-item / option ancestor; it is stable when *other* rows are inserted or removed, so Alice's Edit keeps its ref when Zara is added above her.
- **`act("click")` on iframe elements now lands on the right element.** `ELEMENT_BOUNDS_JS` now walks up frames (via `defaultView.frameElement`) to accumulate iframe offsets, computed fresh at action time. Previously the bbox returned by `_fresh_bounds` was iframe-local, and `page.mouse.click(cx, cy)` clicked the iframe's local coordinates on the top page — usually nothing or the wrong element.
- **`perceive()` no longer mutates nested scroll containers.** v0.1.2 saved and restored the window's `scrollX/Y`, but the per-element `scrollIntoView` also scrolls any overflow:auto|scroll ancestor (and iframe documents). `COLLECT_JS` now snapshots every scroll position that could be touched — same-frame and same-origin nested frames — and restores them all before recomputing bboxes.

### Tests
- `test_adding_sibling_does_not_churn_existing_refs` — regression for the sibling-signature bug.
- `test_inserting_row_does_not_churn_other_rows_refs` — regression for the within-batch occurrence-order bug; verifies `row_context` carries enough identity for repeated table rows.
- `test_iframe_click_actually_lands_on_iframe_element` — clicks an iframe button whose `onclick` sets `parent.window.__iframe_clicked`; asserts the click actually fired.
- `test_perceive_does_not_mutate_nested_scroll_containers` — perceive a deep button inside an overflow:auto div, assert the div's `scrollTop` is unchanged.

## [0.1.2] — 2026-05-13

### Fixed
- **`perceive.__version__` no longer drifts from the package version.** The string is now read from installed package metadata via `importlib.metadata` instead of being hardcoded. Removes the v0.1.1 wheel's incorrect self-report of "0.1.0".
- **`perceive()` no longer mutates page scroll.** The reachability check's per-element `scrollIntoView` shifted the viewport; the final scroll position is now saved at the start of the collect run and restored at the end. Element bboxes are recomputed against the restored scroll so the values returned to the caller match the page state after `perceive()` returns.
- **Bounding boxes for elements inside same-origin iframes are now in top-page viewport coordinates.** Previously the bbox returned for an iframe element was iframe-local, which caused `target.act("click", ref)` to click the wrong position on the top page. The iframe's own `getBoundingClientRect()` offset is now threaded through the recursive collector and added to each element's bbox.

### Tests
- Added `test_perceive_does_not_mutate_scroll` and `test_iframe_element_bbox_is_in_top_page_coords` (e2e).

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

[0.2.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.2.0...v0.2.1
[0.2.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauthierpiarrette/perceive/releases/tag/v0.1.0
