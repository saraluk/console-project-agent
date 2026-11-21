"""One object the console loop talks to: text in, reply out."""

from __future__ import annotations

from datetime import date
from typing import Callable

from .graph.builder import build_graph
from .graph.state import TURN_RESET
from .llm import InputParser
from .storage import ProjectRepository


class ProjectAssistant:
    def __init__(
        self,
        parser: InputParser,
        repo: ProjectRepository,
        thread_id: str = "cli",
        today: Callable[[], date] = date.today,
    ):
        self.graph = build_graph(parser, repo, today=today)
        # The checkpointer keeps draft/awaiting/pending_op between messages for this thread.
        self.config = {"configurable": {"thread_id": thread_id}}

    def handle(self, text: str) -> str:
        result = self.graph.invoke({**TURN_RESET, "user_input": text}, self.config)
        return result.get("response") or "Sorry, I have nothing to say to that."

    @property
    def state(self) -> dict:
        """Current remembered state (handy for tests and debugging)."""
        return dict(self.graph.get_state(self.config).values)
