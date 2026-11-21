"""Functions that pick the next node (used on conditional edges)."""

from __future__ import annotations

from ..models import missing_required
from .state import AgentState

# parse_input's decision -> next node
PARSE_ROUTES = {
    "create": "merge_draft",
    "provide_info": "merge_draft",
    "clarified": "merge_draft",  # answer to "project name or customer?"
    "list": "list_projects",
    "get": "resolve_project",
    "update": "resolve_project",
    "delete": "resolve_project",
    "delete_all": "start_delete_all",
    "delete_all_yes": "confirm_delete_all",  # step 1 passed -> ask for the phrase
    "delete_all_confirmed": "delete_all_projects",  # step 2 passed
    "delete_all_no": "cancel_delete_all",
    "choose": "resolve_project",
    "confirm_yes": "delete_project",
    "confirm_no": "cancel_delete",
    "cancel": "cancel_pending",
    "help": "show_help",
    "unclear": "clarify",
    "error": "finalize",
}

OP_NODES = {"get": "show_project", "update": "update_project", "delete": "confirm_delete"}


def route_after_parse(state: AgentState) -> str:
    return PARSE_ROUTES.get(state.get("route", ""), "clarify")


def check_required(state: AgentState) -> str:
    if state.get("awaiting") == "clarify_field":
        return "ask_clarify"  # a value needs a home before anything is saved
    return "ask_missing" if missing_required(state.get("draft") or {}) else "save_project"


def route_after_resolve(state: AgentState) -> str:
    if state.get("target_id") and state.get("op") in OP_NODES:
        return OP_NODES[state["op"]]
    return "finalize"  # not found / ambiguous / no reference: resolve already replied
