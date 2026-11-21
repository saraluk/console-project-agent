"""The state ("notepad") passed between graph nodes."""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

Awaiting = Literal[
    "fields", "which_project", "confirm_delete", "confirm_delete_all", "clarify_field"
]


class AgentState(TypedDict, total=False):
    # ---- this turn only (reset by ProjectAssistant.handle on every message)
    user_input: str
    parsed: Optional[dict]  # ParsedInput.model_dump()
    route: str  # what parse_input decided to do
    op: Optional[str]  # get / update / delete, once a project is resolved
    target_id: Optional[str]  # resolved project ID
    changes: Optional[dict]  # validated field changes for update
    notes: list[str]  # extra lines shown before the main reply
    response: str  # final text shown to the user
    allow_same: bool  # user confirmed project name and customer really are the same

    # ---- remembered across turns (saved by the checkpointer)
    draft: Optional[dict]  # half-built project waiting for required fields
    awaiting: Optional[Awaiting]  # what question we are waiting on
    # e.g. {"op": "update", "changes": {...}, "candidates": [...]}
    #  or  {"op": "clarify_field", "value": "Dresswell", "fields": ["project_name", "customer"]}
    pending_op: Optional[dict]


TURN_RESET: AgentState = {
    "parsed": None,
    "route": "",
    "op": None,
    "target_id": None,
    "changes": None,
    "notes": [],
    "response": "",
    "allow_same": False,
}
