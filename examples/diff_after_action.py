"""Show ``State.diff()`` detecting elements that change reachability.

Uses the bundled benchmark page 07_closed_drawer.html — the canonical "closed
drawer still in DOM" failure pattern from Playwright #39955: the Close /
Submit buttons exist in the DOM but are translated off-screen until the
drawer opens.

Run:
    pip install perceive
    playwright install chromium
    python examples/diff_after_action.py
"""

from pathlib import Path

import perceive


def main() -> None:
    # Locate the bundled conformance page that ships in the wheel.
    import bench.manifest as m
    page = Path(m.__file__).parent / "pages" / "07_closed_drawer.html"
    url = page.absolute().as_uri()

    with perceive.browser(url=url) as target:
        # Snapshot 1 — drawer closed. Default perceive() hides unreachable.
        s1 = target.perceive()
        print("=== Reachable when drawer is closed ===")
        print(s1.to_prompt())

        # Reveal what was filtered.
        full = target.perceive(include_unreachable=True)
        print(f"\n{sum(1 for e in full if not e.reachable)} unreachable elements filtered:")
        for el in full:
            if not el.reachable:
                print(f"  @{el.ref} {el.role} {el.name!r}")

        # Click the Open Drawer button and wait for the CSS transition (0.3s).
        target.act("click", full.find(name="Open Drawer").ref)
        target.act("wait", 0.5)

        # Snapshot 2 — drawer open. Same refs, but the two drawer buttons
        # flipped from reachable=False to reachable=True.
        s2 = target.perceive(include_unreachable=True)

        diff = s2.diff(full)
        print(f"\n=== Diff after clicking Open Drawer ===")
        print(diff.to_prompt() or "(no changes)")

        transitions = sum(1 for prev, curr in diff.modified
                          if prev.reachable != curr.reachable)
        print(f"\n  added:    {len(diff.added)}")
        print(f"  removed:  {len(diff.removed)}")
        print(f"  modified: {len(diff.modified)}  "
              f"({transitions} are reachable transitions)")


if __name__ == "__main__":
    main()
