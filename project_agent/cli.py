"""The stdin/stdout loop."""

from __future__ import annotations

import logging
import os
from typing import Callable, Protocol

log = logging.getLogger(__name__)

EXIT_WORDS = {"quit", "exit"}
WELCOME = (
    "Project Assistant — manage projects in plain English.\n"
    "Type \"help\" for examples, \"quit\" or \"exit\" to leave."
)


class Assistant(Protocol):
    def handle(self, text: str) -> str: ...


def run(
    assistant: Assistant,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    output_fn(WELCOME)
    while True:
        try:
            line = input_fn("\n> ")
        except (EOFError, KeyboardInterrupt):
            output_fn("\nGoodbye!")
            return

        text = line.strip()
        if not text:
            continue
        if text.casefold() in EXIT_WORDS:
            output_fn("Goodbye!")
            return

        try:
            reply = assistant.handle(text)
        except KeyboardInterrupt:
            output_fn("(interrupted — type \"quit\" to leave)")
            continue
        except Exception as exc:  # never let one bad turn crash the app
            log.debug("Unhandled error", exc_info=True)
            hint = "" if os.getenv("PROJECT_AGENT_DEBUG") else " (set PROJECT_AGENT_DEBUG=1 for details)"
            output_fn(f"Sorry, something went wrong: {type(exc).__name__}. Please try again.{hint}")
            continue

        output_fn(reply)
