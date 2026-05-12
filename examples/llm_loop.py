"""The observe → plan → act → verify loop, with a placeholder LLM call.

This example shows the shape of an agent loop. The ``ask_llm`` function is a
stub that returns a hand-coded response; replace it with a call to whatever
LLM you use (Claude, GPT, Gemini, a local model) and feed `state.to_prompt()`
into the prompt.

Run:
    pip install perceive
    playwright install chromium
    python examples/llm_loop.py
"""

from __future__ import annotations

import perceive


SYSTEM_PROMPT = """You are operating a browser on behalf of a user.

Available actions:
    click(ref)
    type(ref, "text")
    scroll(direction)
    done

Respond with exactly one action per turn, on a single line.
"""


def ask_llm(task: str, state: perceive.State) -> str:
    """Stub: replace with a real LLM call.

    Example with the Anthropic SDK::

        from anthropic import Anthropic
        msg = Anthropic().messages.create(
            model="claude-opus-4-7",
            max_tokens=128,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Task: {task}\\n\\nCurrent UI:\\n{state.to_prompt()}",
            }],
        )
        return msg.content[0].text.strip()
    """
    # Hand-coded response so this example is runnable without an API key.
    link = state.find(name="More information")
    return f"click({link.ref})" if link else "done"


def parse_action(line: str) -> tuple[str, list[str]]:
    """Parse 'click(e1)' or 'type(e2, \"alice\")' into (action, args)."""
    line = line.strip()
    if "(" not in line:
        return line, []
    name, rest = line.split("(", 1)
    rest = rest.rstrip(")").strip()
    args = [a.strip().strip('"') for a in rest.split(",")] if rest else []
    return name.strip(), args


def main() -> None:
    task = "Click the 'More information' link if there is one, then stop."

    with perceive.browser(url="https://example.com") as target:
        for step in range(5):
            state = target.perceive()
            print(f"\n--- step {step+1} ---")
            print(state.to_prompt())

            response = ask_llm(task, state)
            print(f"\nLLM: {response}")
            action, args = parse_action(response)

            if action == "done":
                print("\nLLM signaled completion.")
                return
            if action == "click" and args:
                with target.observe_change() as obs:
                    target.act("click", args[0])
                print(f"\nDiff after click:\n{obs.diff.to_prompt() or '(no diff)'}")
            elif action == "type" and len(args) >= 2:
                target.act("type", args[0], args[1])
            elif action == "scroll" and args:
                target.act("scroll", direction=args[0])
            else:
                print(f"Unknown action: {response!r}; stopping.")
                return


if __name__ == "__main__":
    main()
