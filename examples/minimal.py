"""The smallest useful perceive program.

Open a page, perceive it, click the first link, observe the change.

Run:
    pip install perceive
    playwright install chromium
    python examples/minimal.py
"""

import perceive


def main() -> None:
    with perceive.browser(url="https://example.com") as target:
        state = target.perceive()
        print(f"Found {len(state)} reachable elements:")
        print(state.to_prompt())

        link = state.find(name="More information")
        if link is None:
            print("\nNo 'More information' link on this page; nothing to click.")
            return

        print(f"\nClicking @{link.ref}: {link.role} {link.name!r}")
        with target.observe_change() as obs:
            target.act("click", link.ref)

        print(f"\nAfter clicking, the page changed by:")
        print(obs.diff.to_prompt() or "(no visible diff)")


if __name__ == "__main__":
    main()
