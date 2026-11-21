"""Wire the nodes and edges into a LangGraph StateGraph."""

from __future__ import annotations

from datetime import date
from typing import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..llm import InputParser
from ..storage import ProjectRepository
from .nodes import Nodes
from .routing import OP_NODES, PARSE_ROUTES, check_required, route_after_parse, route_after_resolve
from .state import AgentState


def build_graph(
    parser: InputParser,
    repo: ProjectRepository,
    checkpointer: BaseCheckpointSaver | None = None,
    today: Callable[[], date] = date.today,
):
    nodes = Nodes(parser, repo, today=today)
    g = StateGraph(AgentState)

    for name in (
        "parse_input",
        "merge_draft",
        "ask_clarify",
        "ask_missing",
        "save_project",
        "list_projects",
        "resolve_project",
        "show_project",
        "update_project",
        "confirm_delete",
        "delete_project",
        "cancel_delete",
        "start_delete_all",
        "confirm_delete_all",
        "delete_all_projects",
        "cancel_delete_all",
        "cancel_pending",
        "show_help",
        "clarify",
        "finalize",
    ):
        g.add_node(name, getattr(nodes, name))

    g.add_edge(START, "parse_input")
    g.add_conditional_edges("parse_input", route_after_parse, sorted(set(PARSE_ROUTES.values())))

    # Create flow: merge -> (ambiguous? clarify : missing? ask : save)
    g.add_conditional_edges(
        "merge_draft", check_required, ["ask_clarify", "ask_missing", "save_project"]
    )

    # Existing-project flow: resolve -> get/update/delete (or finalize if not resolved)
    g.add_conditional_edges(
        "resolve_project", route_after_resolve, [*OP_NODES.values(), "finalize"]
    )

    for name in (
        "ask_clarify",
        "ask_missing",
        "save_project",
        "list_projects",
        "show_project",
        "update_project",
        "confirm_delete",
        "delete_project",
        "cancel_delete",
        "start_delete_all",
        "confirm_delete_all",
        "delete_all_projects",
        "cancel_delete_all",
        "cancel_pending",
        "show_help",
        "clarify",
    ):
        g.add_edge(name, "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
