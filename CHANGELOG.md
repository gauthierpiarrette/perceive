# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] — 2026-05-14

### Docs
- README: sharper opening hook; added plain-text comparison block above the benchmark table; tightened footnotes and benchmark prose; hardened `git clone` URL; roadmap items reformatted for readability.

## [0.3.1] — 2026-05-13

### Added
- **5 real component-library bench pages** in `bench/pages/`: Radix Dialog (`15`), MUI Modal (`16`), Ant Design Drawer open state (`17`, the canonical component referenced in Playwright #39955), Headless UI Combobox closed state (`18`), and a long scrollable list with repeated `Edit` buttons (`19`). The corpus is now 19 pages / 60 ground-truth labels (was 14 / 36).

### Fixed
- **Reachability check no longer rejects elements whose ancestor has `pointer-events: none`.** Per CSS spec a descendant with `pointer-events: auto` (or default) is a valid hit-test target even when an ancestor has `pointer-events: none`. The previous implementation walked the ancestor chain and rejected on any `pointer-events: none`, which broke patterns like Ant Design's drawer where `.ant-drawer` has `pointer-events: none` so background clicks pass through and `.ant-drawer-content-wrapper` has `pointer-events: auto` so its children can still receive clicks. Now we check only the element's own computed `pointer-events`; inheritance is reflected in `getComputedStyle` so `inherit`-from-`none` is still correctly rejected. Verified by page `17_antd_drawer_open` and regression-protected by the existing `04_pointer_events_none` page.

### Benchmark — updated head-to-head

Numbers on the new 19-page corpus (60 ground-truth labels, 34 reachable / 26 unreachable):

| Adapter | Precision | F1 | Unreachable wrongly surfaced | Median `to_prompt()` tokens / page | Median cold-call latency |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline | 0.567 | 0.723 | 26 / 26 | 26 | 1844 ms |
| Playwright MCP (`@playwright/mcp`) | 0.654 | 0.791 | 18 / 26 | 195 | 3548 ms |
| `perceive` | 1.000 | 1.000 | 0 / 26 | 14 | 1657 ms |

Six of the additional Playwright MCP false positives (12 → 18) come from the new component-library pages — confirming the failure pattern documented in Playwright #39955 reproduces on real Radix, MUI, and Ant Design DOM, not only synthetic test pages.

### Docs
- README: section heading `## Limitations (v0.1)` → `## Limitations`; updated stale version-pinned roadmap items; benchmark table now includes `Median cold-call latency`, drops `Recall` (1.000 across all adapters), uses `Unreachable wrongly surfaced` for clarity; added a token-counting methodology footnote; added a side-by-side terminal-output block under the table; example uses `el.unreachable_reason` to show the v0.2.0 debug capability.

## [0.3.0] — 2026-05-13

### Added
- **Playwright MCP bench adapter** (`bench/adapters/playwright_mcp.py`) — drives Microsoft's `@playwright/mcp` server via stdio JSON-RPC. Subprocess-per-page, matching the isolation pattern of the other bench adapters. Requires Node.js + `npx`; override the binary with `PERCEIVE_NPX`, the first-run timeout with `PERCEIVE_MCP_TIMEOUT`.
- **Snapshot parser** for Playwright MCP's YAML-ish aria-tree output (`_parse_snapshot`), with parser-level unit tests in `tests/test_playwright_mcp_parser.py`. The parser is liberal — any line with a `[ref=...]` tag is captured — but drops unnamed structural roles so they do not pollute the matcher.

### Benchmark — first head-to-head

| Adapter | Precision | Recall | F1 | False positives (36) | Median tokens / page |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline | 0.528 | 1.000 | 0.691 | 17 | 21.5 |
| Playwright MCP (`@playwright/mcp`) | 0.613 | 1.000 | 0.760 | 12 | 180.5 |
| `perceive` | 1.000 | 1.000 | 1.000 | 0 | 8.0 |

Playwright MCP correctly filters elements the underlying Chromium accessibility tree already excludes (`display:none`, `visibility:hidden`, `pointer-events:none`, `disabled`, `shadow_dom`, `iframe`). The 12 false positives are concentrated on patterns the a11y tree alone cannot resolve — modal occlusion (pages 7, 8, 9), off-screen transform (pages 5, 6), inert subtrees (pages 10, 11), and the `opacity:0` edge (page 3) — i.e. exactly the patterns documented in Playwright issue #39955.

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

[0.3.2]: https://github.com/gauthierpiarrette/perceive/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/gauthierpiarrette/perceive/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/gauthierpiarrette/perceive/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/gauthierpiarrette/perceive/releases/tag/v0.1.0
