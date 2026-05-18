<div align="center">

<img src="https://raw.githubusercontent.com/gauthierpiarrette/perceive/main/assets/logo-v2.png" alt="perceive" width="320">

**AI browser agents click things that aren't actually clickable.**

[![Star perceive on GitHub](https://img.shields.io/badge/Star%20on%20GitHub-1f6feb?style=for-the-badge&logo=github&logoColor=white)](https://github.com/gauthierpiarrette/perceive)

[![Tests](https://github.com/gauthierpiarrette/perceive/actions/workflows/test.yml/badge.svg)](https://github.com/gauthierpiarrette/perceive/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perceive)](https://pypi.org/project/perceive/)
[![Python](https://img.shields.io/pypi/pyversions/perceive)](https://pypi.org/project/perceive/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/gauthierpiarrette/perceive/blob/main/LICENSE)

</div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gauthierpiarrette/perceive/main/assets/overview-dark.png">
  <img alt="perceive filters raw browser state (closed drawers, modal-occluded controls, off-screen elements) into a compact reachable action space the agent consumes." src="https://raw.githubusercontent.com/gauthierpiarrette/perceive/main/assets/overview-light.png">
</picture>

`perceive` is a Python library that gives browser agents a reachability-filtered action space. Closed drawers, modal-occluded buttons, `inert` subtrees, off-screen transforms: gone before the model sees the snapshot. The result is compact and ref-stable, with `state.diff()` to confirm what changed after each action.

- **Fewer wrong actions.** The model only sees elements a user could actually reach, so it stops trying to click controls behind modals or inside closed drawers. `perceive` surfaces 0 of 26 unreachable elements; other browser-agent tools surface 15 to 18.
- **Fewer tokens.** The snapshot is just the reachable action space, nothing else: 14 tokens per page, against 52 to 195 for other browser-agent tools.

Use it as a Python library, or run it as an [MCP server](#mcp-server) so clients like Claude Code, Claude Desktop, and Cursor can drive a browser with no code.

## Quickstart

```bash
pip install perceive
playwright install chromium    # ~100 MB Chromium binary
```

```python
import perceive

with perceive.browser(url="https://example.com") as t:
    state = t.perceive()
    print(state.to_prompt())
    # @e1 link "More information..."

    t.act("click", state.find(name="More information").ref)
```

## Benchmark results

Measured on a 19-page hand-labeled reachability conformance suite (`bench/`): 14 synthetic patterns plus 5 real-world component-library cases (Radix Dialog, MUI Modal, Ant Design Drawer, Headless UI Combobox, scrollable list with repeated actions). Same machine, same conformance pages, same 60 ground-truth labels (34 reachable, 26 unreachable); each tool drives the browser it ships with:

**Three browser-agent observation tools each surface 15 to 18 of 26 unreachable elements as valid agent actions; `perceive` surfaces 0.**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gauthierpiarrette/perceive/main/assets/benchmark-dark.png">
  <img alt="Browser-agent observation tools expose unreachable actions. False-positive actions out of 26: Playwright MCP 18, Chrome DevTools MCP 15, Vercel agent-browser 15, perceive 0. Median observation tokens per page: Playwright MCP 195, Chrome DevTools MCP 153, Vercel agent-browser 52, perceive 14." src="https://raw.githubusercontent.com/gauthierpiarrette/perceive/main/assets/benchmark-light.png">
</picture>

| Adapter | Precision | F1 | False-positive actions | Median observation tokens / page | Median cold-call latency |
|---|---:|---:|---:|---:|---:|
| Raw a11y baseline (no reachability filtering) | 0.567 | 0.723 | 26 / 26 | 26 | 1363 ms |
| Playwright MCP (`@playwright/mcp`) | 0.654 | 0.791 | 18 / 26 | 195 | 3938 ms |
| Chrome DevTools MCP (`chrome-devtools-mcp`) | 0.694 | 0.819 | 15 / 26 | 153 | 6937 ms |
| Vercel agent-browser (`agent-browser`) | 0.694 | 0.819 | 15 / 26 | 52 | 2287 ms |
| **`perceive`** | **1.000** | **1.000** | **0 / 26** | **14** | **1605 ms** |

The three browser-agent tools miss the same geometry the accessibility tree doesn't encode: modal occlusion, sticky-header overlap, off-screen transforms, parent-overflow clipping. The gap is reachability, not snapshot size. `perceive` runs an explicit reachability pass and resolves all of them, deterministically: 1.000 exact match across 19 pages × 5 runs.

*Recall is 1.000 for all five adapters, so the gap is precision, not coverage. Tokens count the agent-facing snapshot only (each tool's native snapshot call), prompt context excluded. Latency is per-call wall time including a fresh browser launch, which a long-lived server would mostly amortize away.*

**Scope of claim.** This is a reachability conformance benchmark, not a general claim about Playwright. Playwright remains the execution layer `perceive`'s browser backend builds on; this measures the *observation* layer.

## Three things `perceive` does that a raw accessibility tree does not

### 1. Filter unreachable elements

```python
import perceive

# A closed drawer is still in the DOM, just translated off-screen.
# A raw a11y tree includes its buttons. perceive does not.
with perceive.browser(url="https://your-app.com") as t:
    state = t.perceive()
    print(len(state.elements))                                    # 4 visible buttons
    state_full = t.perceive(include_unreachable=True)
    print(len(state_full.elements))                                # 7 (visible + drawer contents)
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

Playwright locators are the right tool when *you already know what to interact with*. You write `page.get_by_role("button", name="Sign in")` because you, the human author, decided that button is what you want.

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

## MCP server

`perceive` ships an MCP server, so any MCP client (Claude Code, Claude Desktop, Cursor) can drive a browser through the same reachability-filtered action space without writing any Python.

```bash
pip install 'perceive[mcp]'
playwright install chromium
```

Register it with your MCP client (stdio transport):

```json
{
  "mcpServers": {
    "perceive": {
      "command": "perceive-mcp"
    }
  }
}
```

That assumes `perceive-mcp` is on your `PATH`. If it isn't, or you would rather not install it globally, run it with [`uvx`](https://docs.astral.sh/uv/) instead:

```json
{
  "mcpServers": {
    "perceive": {
      "command": "uvx",
      "args": ["--from", "perceive[mcp]", "perceive-mcp"]
    }
  }
}
```

The server exposes six tools:

| Tool | What it does |
|---|---|
| `navigate(url)` | Open a URL; returns the reachability-filtered snapshot |
| `perceive()` | Re-observe the current page |
| `click(ref)` | Click an element by ref |
| `type(ref, text)` | Type text into an element by ref |
| `scroll(direction, amount)` | Scroll the page |
| `press(key)` | Press a key (`Enter`, `Tab`, ...) |

`navigate` and `perceive` return the full compact snapshot; the four action tools return a diff of what changed, so the model sees only the delta after each step.

Benchmarked through the MCP transport, `perceive`'s server scores the same 0 / 26 false positives and 14 median tokens as the library (`bench/adapters/perceive_mcp.py`). The reachability result is unchanged by MCP, and because the server keeps the browser warm across tool calls, the browser-launch cost is paid once per session rather than per call.

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

- **Browser only.** A macOS backend (`perceive.macos()`) is planned but not yet implemented.
- **Chromium only.** Firefox and WebKit are untested against the benchmark suite.
- **No vision fallback.** Canvas-heavy UIs, custom widgets without ARIA, and image-only elements return as fewer (or zero) elements. A small-VLM fallback is planned.
- **Cross-origin iframes and closed Shadow DOM are opaque** (browser security, and `{ mode: 'closed' }` by design). Same-origin iframes and open shadow roots work.
- **Ref stability is exact-fingerprint based.** A button whose accessible name changes mid-session ("Save" → "Saving…") gets a new ref. Scored-similarity matching is planned.
- **Benchmark is 19 pages and three external tools.** It covers CSS hiding, positioning, occlusion, traversal (Shadow DOM + iframe), and real component libraries (Radix, MUI, Ant Design, Headless UI); it does not yet cover virtualized lists, portals, nested modals, or cookie banners. Expanding before any "production-ready" claim.

## Reproducing the benchmarks

The repo includes a `bench` package. To run it yourself:

```bash
git clone https://github.com/gauthierpiarrette/perceive.git
cd perceive
pip install -e ".[bench,dev]"
playwright install chromium

perceive-bench list pages
perceive-bench list adapters

# Run the head-to-head against the other tools yourself.
# Requires Node.js + npx; the first invocation downloads each package.
# chrome_devtools_mcp and agent_browser also need a local Chrome to drive
# (agent-browser: `npm i -g agent-browser && agent-browser install`).
perceive-bench run --adapter playwright_mcp --suite reachability
perceive-bench run --adapter playwright_mcp --suite tokens
perceive-bench run --adapter chrome_devtools_mcp --suite reachability
perceive-bench run --adapter chrome_devtools_mcp --suite tokens
perceive-bench run --adapter agent_browser --suite reachability
perceive-bench run --adapter agent_browser --suite tokens

# Same against perceive.
perceive-bench run --adapter perceive --suite reachability
perceive-bench run --adapter perceive --suite tokens
perceive-bench run --adapter perceive --suite determinism --runs 5
```

All results are written to `results/` as JSON.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
