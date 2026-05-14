# perceive

A Python library that turns a browser page into a compact, ref-stable, reachability-filtered structured snapshot for AI agents.

AI browser agents that read raw accessibility trees end up trying to click elements that exist in the DOM but cannot actually be interacted with — closed drawers, modal-occluded buttons, `inert` subtrees, off-screen transforms. `perceive` filters those out, gives the model compact stable refs, and lets agents diff UI state between actions.

```python
import perceive

with perceive.browser(url="https://example.com") as t:
    state = t.perceive()
    print(state.to_prompt())
    # @e1 link "More information..."

    t.act("click", state.find(name="More information").ref)
```

## Benchmark results

Measured on a 19-page hand-labeled reachability conformance suite (`bench/`) — 14 synthetic patterns plus 5 real-world component-library cases (Radix Dialog, MUI Modal, Ant Design Drawer, Headless UI Combobox, scrollable list with repeated actions). Same machine, same Chromium build, same 60 ground-truth labels (34 reachable, 26 unreachable):

**Playwright MCP surfaces 18 elements an AI agent cannot actually interact with; `perceive` surfaces 0.**

| Adapter | Precision | F1 | False-positive actions | Median observation tokens / page | Median cold-call latency |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline (no reachability filtering) | 0.567 | 0.723 | 26 / 26 | 26 | 1844 ms |
| Playwright MCP (`@playwright/mcp`) | 0.654 | 0.791 | 18 / 26 | 195 | 3548 ms |
| **`perceive`** | **1.000** | **1.000** | **0 / 26** | **14** | **1657 ms** |

*All three adapters preserve **recall at 1.000** — every reachable element in the ground truth is surfaced by every adapter. The precision gap is entirely about which **unreachable** elements get filtered, not about hiding reachable ones.*

```text
$ perceive-bench run --adapter playwright_mcp --suite reachability
  precision : 0.654    FP: 18 / 26    median tokens: 195    median cold-call latency: 3548 ms

$ perceive-bench run --adapter perceive --suite reachability
  precision : 1.000    FP:  0 / 26    median tokens:  14    median cold-call latency: 1657 ms
```

*Observation tokens measure only the agent-facing snapshot text each adapter emits — for `perceive`, the output of `state.to_prompt()`; for Playwright MCP, the `browser_snapshot` text. Task instructions and surrounding prompt context are excluded. Latency is per-call wall time including subprocess startup: both adapters launch a fresh browser process per page (the bench isolates each call), so a long-lived MCP server would amortize startup across many calls and the warm-state latency gap is smaller than the cold-call numbers above. The token and false-positive numbers are unaffected by warm-vs-cold operation.*

Each false positive is an element an AI agent may try to click and fail on — the failure pattern documented in [Playwright issue #39955](https://github.com/microsoft/playwright/issues/39955), now reproduced not just on synthetic test pages but on the real DOM emitted by Radix, MUI, and Ant Design components.

Playwright MCP already filters elements Chromium's accessibility tree excludes (CSS-hidden such as `display:none` / `visibility:hidden`, plus disabled controls and most non-focusable elements), beating the raw baseline by 8. The remaining 18 unreachable elements it surfaces fall into patterns the accessibility tree alone cannot resolve: modal occlusion, sticky-header overlap, off-screen transforms, `inert` subtrees, and `aria-hidden` cascades — including the Radix Dialog, MUI Modal, and the Ant Design Drawer (the canonical component referenced in Playwright #39955). `perceive` performs an explicit reachability pass over these and eliminates them all.

Determinism: 1.000 mean exact-match rate for `perceive` across 19 pages × 5 runs each.

**Scope of claim.** This is a reachability conformance benchmark, not a general claim about Playwright. Playwright remains the underlying execution layer that `perceive`'s browser backend builds on; this benchmark measures the *observation* layer — what an agent sees before it decides what to do.

Bench adapters for Chrome DevTools MCP and Vercel agent-browser are still on the roadmap.

## Install

```bash
pip install perceive
playwright install chromium    # ~100 MB Chromium binary
```

## Three things `perceive` does that a raw accessibility tree does not

### 1. Filter unreachable elements

```python
import perceive

# A closed drawer is still in the DOM, just translated off-screen.
# A raw a11y tree includes its buttons. perceive does not.
with perceive.browser(url="https://your-app.com") as t:
    state = t.perceive()
    print(len(state.elements))                                    # 4 — the visible buttons
    state_full = t.perceive(include_unreachable=True)
    print(len(state_full.elements))                                # 7 — visible + drawer contents
    for el in state_full.elements:
        if not el.reachable:
            print(f"  filtered: {el.role} {el.name!r} ({el.unreachable_reason})")
    # filtered: button 'Close Drawer' (offscreen)
    # filtered: button 'Submit Form' (offscreen)
```

### 2. Filter modal-occluded elements

```python
# Buttons behind an open modal are present in the DOM and the a11y tree,
# but a real user cannot click them. perceive returns only the modal's buttons.
with perceive.browser(url="https://your-app.com") as t:
    state = t.perceive()
    for el in state:
        print(el.ref, el.role, repr(el.name))
    # e1 button 'OK'        (in the modal)
    # e2 button 'Cancel'    (in the modal)
    # the two background buttons are filtered out
```

### 3. Stable refs across reflows, including for repeated elements

```python
with perceive.browser(url="https://your-app.com/users") as t:
    state = t.perceive()

    # Repeated buttons with the same label get distinct refs, disambiguated
    # by surrounding context (parent landmark, siblings, stable attributes):
    edits = state.find_all(name="Edit")
    print([e.ref for e in edits])
    # ['e3', 'e5', 'e7']

    # An element's ref is preserved across re-perceives, including after
    # scrolling and other reflows that keep the element in the document:
    sign_in_before = state.find(name="Sign in").ref
    t.act("scroll", direction="down", amount=400)
    sign_in_after = t.perceive().find(name="Sign in").ref
    assert sign_in_before == sign_in_after
```

## Why not just use Playwright locators?

Playwright locators are the right tool when *you already know what to interact with* — you write `page.get_by_role("button", name="Sign in")` because you, the human author, decided that button is what you want.

`perceive` is for the part of an agent loop where *the model* needs to decide what's available. The flow is **observe → plan → act → verify**, and step 1 is "give the model a compact, reachable, ref-stable action space." `perceive` does that step; it doesn't replace deterministic Playwright tests for code you've already written.

## Integration: feeding `perceive` output to an LLM

```python
import perceive

with perceive.browser(url="https://app.example.com/login") as target:
    state = target.perceive()

    prompt = f"""You are operating a browser. Available actions:
- click(ref)
- type(ref, text)
- scroll(direction)

Current UI:
{state.to_prompt()}

Task: sign in as alice@example.com with password hunter2.
Respond with one action per line."""

    # Send `prompt` to any LLM (Claude, GPT, Gemini, local model).
    # Parse the response into actions, then call:
    target.act("type", "e2", "alice@example.com")
    target.act("type", "e3", "hunter2")

    # Use observe_change to see the result of the click in compact form.
    with target.observe_change() as obs:
        target.act("click", state.find(name="Sign in").ref)
    print(obs.diff.to_prompt())
    # +@e7 dialog "Welcome back, Alice"
    # -@e3 textbox "Password"
    # … 5 unchanged
```

## API

```python
target = perceive.browser(url=None, *, headless=True, viewport=(1280, 800))

# Navigation and lifecycle
target.goto(url)
target.close()                                  # or use as a context manager

# Perception
state = target.perceive(
    region=None,                # CSS selector or (x, y, w, h) bbox to scope
    role=None,                  # filter to a single role (e.g. "button")
    include_text=False,         # reserved; not yet implemented
    include_unreachable=False,  # default: filter unreachable
)

# State
state.elements                  # list[Element]
state.find(ref=..., role=..., name=..., reachable=...)
state.find_all(role=..., name=..., reachable=...)
state.to_prompt(only_reachable=True)
state.diff(previous)            # DiffResult

# Action (shares ref space with the most recent perceive())
target.act("click", ref)
target.act("type", ref, text)
target.act("set_value", ref, text)            # programmatic, for tricky inputs
target.act("scroll", direction="down", amount=400)
target.act("press", key)                       # e.g. "Enter", "Tab"
target.act("goto", url)
target.act("wait", seconds)

# Self-verifying loop
with target.observe_change(settle_ms=200) as obs:
    target.act("click", "e1")
obs.before, obs.after, obs.diff
```

## Limitations

This is a deliberately narrow early release. Things `perceive` does **not** do yet:

- **Browser only.** A macOS backend (`perceive.macos()`) is on the roadmap but not yet implemented.
- **Chromium only.** Playwright supports Firefox and WebKit but neither is tested against the benchmark suite.
- **No vision fallback.** Canvas-heavy UIs, custom widgets without ARIA, and image-only elements will return as fewer (or zero) elements. A small-VLM fallback is on the roadmap.
- **Cross-origin iframes cannot be introspected** (browser security; same-origin iframes work).
- **Closed Shadow DOM cannot be traversed** (`{ mode: 'closed' }` is opaque by design). Open shadow roots work.
- **Ref stability is exact-fingerprint based.** A button whose accessible name changes mid-session ("Save" → "Saving…") will get a new ref. Scored-similarity matching is on the roadmap.
- **Benchmark is 19 pages.** Patterns covered: CSS hiding, positioning, occlusion, ancestor attributes, traversal (Shadow DOM + iframe), non-interactive controls, and the real DOM emitted by Radix Dialog, MUI Modal, Ant Design Drawer, Headless UI Combobox, and a long scrollable list. Patterns not yet covered: virtualized lists with off-DOM rows, portals, nested modals, cookie banners, animated layout shift. Expanding before any "production-ready" claim.
- **Bench adapters for Chrome DevTools MCP and Vercel agent-browser are not yet implemented.** The Playwright MCP adapter ships in `bench/adapters/`.

## Reproducing the benchmarks

The repo includes a `bench` package. To run it yourself:

```bash
git clone <repo-url>
cd perceive
pip install -e ".[bench,dev]"
playwright install chromium

perceive-bench list pages
perceive-bench list adapters

# Run the head-to-head against Playwright MCP yourself
# (the first invocation downloads @playwright/mcp via npx — Node.js + npx required):
perceive-bench run --adapter playwright_mcp --suite reachability
perceive-bench run --adapter playwright_mcp --suite tokens

# Same against perceive
perceive-bench run --adapter perceive --suite reachability
perceive-bench run --adapter perceive --suite tokens
perceive-bench run --adapter perceive --suite determinism --runs 5
```

All results are written to `results/` as JSON.

## Roadmap

Ordered by priority; version assignments are deliberately unpinned because the v0.1 → v0.3 sequence already taught us that pinning features to specific versions is a promise the codebase will break.

- **Next** — Bench adapters for Chrome DevTools MCP and Vercel agent-browser; expanded conformance corpus (virtualized lists with off-DOM rows, portals, nested modals, cookie banners, animated layout shift).
- **Then** — `include_text=True` body capture; scored-similarity ref matching so elements whose accessible name changes mid-session keep their refs; an MCP server adapter so non-Python agents can consume `perceive` directly.
- **Later** — Experimental desktop perception: macOS (AXUIElement), Windows (UIA), Linux (AT-SPI), all behind the same `State` / `Element` shape. Read-only first; desktop `act()` ships separately.
- **Beyond** — Vision fallback as a plugin API (`target.set_vision_backend(...)`), with a first small-VLM backend for canvas-heavy and non-accessible regions.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
