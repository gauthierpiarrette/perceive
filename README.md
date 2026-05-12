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

Measured on a 14-page hand-labeled reachability conformance suite (`bench/`).

The baseline is intentionally simple: it returns raw accessibility candidates without a reachability pass. This models the failure pattern documented in [Playwright issue #39955](https://github.com/microsoft/playwright/issues/39955): elements may appear in an accessibility snapshot even when they are hidden, inert, off-screen, or occluded.

Direct adapters for Playwright MCP, Chrome DevTools MCP, and Vercel agent-browser are not implemented yet, so these are not head-to-head claims against those tools.

| Adapter | Precision | Recall | F1 | False positives | Median `to_prompt()` tokens / page |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline (no reachability filtering) | 0.528 | 1.000 | 0.691 | 17 / 36 | 21.5 |
| **`perceive`** | **1.000** | **1.000** | **1.000** | **0 / 36** | **8.0** |

Each false positive in the baseline is an element an AI agent may try to click and fail on. Determinism: 1.000 mean exact-match rate across 14 pages × 5 runs each.

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
            print(f"  filtered: {el.role} {el.name!r}")
    # filtered: button 'Close Drawer'
    # filtered: button 'Submit Form'
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
    include_text=False,         # reserved for v0.2
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

## Limitations (v0.1)

This is a deliberately narrow first release. Things `perceive` does **not** do yet:

- **Browser only.** Spec includes a macOS backend (`perceive.macos()`); it is not in v0.1. Coming in v0.3.
- **Chromium only.** Playwright supports Firefox and WebKit but neither is tested against the benchmark suite.
- **No vision fallback.** Canvas-heavy UIs, custom widgets without ARIA, and image-only elements will return as fewer (or zero) elements. A small-VLM fallback is on the v0.4 roadmap.
- **Cross-origin iframes cannot be introspected** (browser security; same-origin iframes work).
- **Closed Shadow DOM cannot be traversed** (`{ mode: 'closed' }` is opaque by design). Open shadow roots work.
- **Ref stability is exact-fingerprint based.** A button whose accessible name changes mid-session ("Save" → "Save (1)") will get a new ref. Scored-similarity matching is on the v0.2 roadmap.
- **Benchmark is 14 pages.** Patterns covered: CSS hiding, positioning, occlusion, ancestor attributes, traversal (Shadow DOM + iframe), and non-interactive controls. Patterns not yet covered: virtualized lists, portals, nested modals, cookie banners, real component-library frameworks (Radix, MUI, Ant Design, Headless UI). Expanding before any "production-ready" claim.
- **No direct adapter for Playwright MCP, Chrome DevTools MCP, or Vercel agent-browser** in the benchmark yet. Until those exist, comparison is to the raw-a11y-tree baseline (which is the documented failure pattern of those tools, but not a head-to-head measurement).

## Reproducing the benchmarks

The repo includes a `bench` package. To run it yourself:

```bash
git clone <repo-url>
cd perceive
pip install -e ".[bench,dev]"
playwright install chromium

perceive-bench list pages
perceive-bench run --adapter perceive --suite reachability
perceive-bench run --adapter perceive --suite tokens
perceive-bench run --adapter perceive --suite determinism --runs 5
```

All results are written to `results/` as JSON.

## Roadmap

The next milestone is making the browser wedge undeniable — broader bench coverage and head-to-head numbers — before broadening the platform surface.

- **v0.1.x** — Benchmark expansion (Radix, MUI, Ant Design, Headless UI, virtualized lists, portals, cookie banners, nested modals) and direct adapters in `bench/` for Playwright MCP, Chrome DevTools MCP, and Vercel agent-browser. Goal: head-to-head reachability and token numbers.
- **v0.2** — `include_text=True` body capture, scored-similarity ref matching for elements whose accessible name changes mid-session, and an MCP server adapter so non-Python agents can consume `perceive` directly.
- **v0.3** — Experimental desktop perception: macOS (AXUIElement), Windows (UIA), Linux (AT-SPI), all behind the same `State` / `Element` shape. Read-only first; desktop `act()` ships separately.
- **v0.4** — Vision fallback as a plugin API (`target.set_vision_backend(...)`), with a first small-VLM backend for canvas-heavy and non-accessible regions.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
