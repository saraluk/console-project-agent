"""A stand-in for the LLM so tests run offline and deterministically."""

from __future__ import annotations

from project_agent.llm import LLMUnavailableError
from project_agent.models import ParsedInput

P = ParsedInput.make  # shorthand: P("create", project_name="X", customer="Y")


class FakeParser:
    """Returns scripted ParsedInput objects keyed by the exact user text."""

    def __init__(self, script: dict[str, ParsedInput] | None = None):
        self.script = dict(script or {})
        self.calls: list[tuple[str, str]] = []  # (text, context) seen by the "LLM"
        self.down = False  # simulate OpenRouter being unreachable

    def parse(self, text: str, context: str) -> ParsedInput:
        self.calls.append((text, context))
        if self.down:
            raise LLMUnavailableError("I couldn't reach the language model just now.")
        return self.script.get(text, P("unclear"))
