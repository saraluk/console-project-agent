"""Data models: stored projects and the LLM's structured reading of user input."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

REQUIRED_FIELDS = ("project_name", "customer")
OPTIONAL_FIELDS = ("start_date", "location", "status", "notes")
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

STATUSES = ("planned", "active", "on_hold", "completed", "cancelled")
_STATUS_SYNONYMS = {
    "planning": "planned",
    "not started": "planned",
    "new": "planned",
    "in progress": "active",
    "in-progress": "active",
    "ongoing": "active",
    "started": "active",
    "on hold": "on_hold",
    "on-hold": "on_hold",
    "paused": "on_hold",
    "done": "completed",
    "complete": "completed",
    "finished": "completed",
    "canceled": "cancelled",
}

FIELD_LABELS = {
    "project_name": "project name",
    "customer": "customer",
    "start_date": "start date",
    "location": "location",
    "status": "status",
    "notes": "notes",
}

FieldName = Literal["project_name", "customer", "start_date", "location", "status", "notes"]

Intent = Literal[
    "create",
    "provide_info",
    "list",
    "get",
    "update",
    "delete",
    "delete_all",
    "choose",
    "cancel",
    "help",
    "unclear",
]


# --------------------------------------------------------------------------- #
# Stored project
# --------------------------------------------------------------------------- #
class Project(BaseModel):
    id: str
    project_name: str = Field(min_length=1)
    customer: str = Field(min_length=1)
    start_date: Optional[str] = None  # ISO YYYY-MM-DD
    location: Optional[str] = None
    status: Optional[Literal["planned", "active", "on_hold", "completed", "cancelled"]] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str

    @field_validator("start_date")
    @classmethod
    def _iso_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return date.fromisoformat(value).isoformat()


# --------------------------------------------------------------------------- #
# LLM structured output
# Every field is required-but-nullable (no defaults) so the JSON schema is
# valid for OpenAI-style strict structured outputs.
# --------------------------------------------------------------------------- #
class ProjectFields(BaseModel):
    """Project details mentioned in the message. Use null for anything not said."""

    project_name: Optional[str] = Field(description="Project name/title, or null")
    customer: Optional[str] = Field(description="Customer/client name, or null")
    start_date: Optional[str] = Field(description="Start date as YYYY-MM-DD, or null")
    location: Optional[str] = Field(description="Location, or null")
    status: Optional[str] = Field(
        description="One of planned, active, on_hold, completed, cancelled, or null"
    )
    notes: Optional[str] = Field(description="Extra notes, or null")


class ParsedInput(BaseModel):
    """Structured interpretation of one user message."""

    intent: Intent = Field(description="What the user wants to do")
    fields: ProjectFields = Field(
        description="Project details: for create/provide_info the details given; "
        "for update only the NEW values"
    )
    project_ref: Optional[str] = Field(
        description="For get/update/delete: the existing project's ID or name. Otherwise null"
    )
    choice: Optional[str] = Field(
        description="For choose: the project ID or list number picked. Otherwise null"
    )
    clear_fields: list[FieldName] = Field(
        description="Draft fields the user says are wrong or should be removed "
        "(e.g. 'X is not the project name'). Empty list if none"
    )
    start_date_text: Optional[str] = Field(
        description="The user's exact words for the start date (e.g. 'next Monday', "
        "'in 2 weeks', 'Dec 3'), copied from the message. Otherwise null"
    )
    ambiguous_value: Optional[str] = Field(
        description="A value the user gave when it is unclear which field it belongs to "
        "(e.g. a bare name that could be the project name or the customer). "
        "Do not also put it in fields. Otherwise null"
    )

    @classmethod
    def make(
        cls,
        intent: str,
        project_ref: Optional[str] = None,
        choice: Optional[str] = None,
        clear_fields: Optional[list[str]] = None,
        ambiguous_value: Optional[str] = None,
        start_date_text: Optional[str] = None,
        **fields: Optional[str],
    ) -> "ParsedInput":
        """Convenience constructor (used by tests and fast paths)."""
        full = {name: fields.get(name) for name in ALL_FIELDS}
        return cls(
            intent=intent,  # type: ignore[arg-type]
            fields=ProjectFields(**full),
            project_ref=project_ref,
            choice=choice,
            clear_fields=list(clear_fields or []),  # type: ignore[arg-type]
            ambiguous_value=ambiguous_value,
            start_date_text=start_date_text,
        )


# --------------------------------------------------------------------------- #
# Field cleaning / validation helpers
# --------------------------------------------------------------------------- #
_ID_RE = re.compile(r"^p-?0*(\d+)$", re.IGNORECASE)


def format_id(number: int) -> str:
    return f"P-{number:03d}"


def normalize_id(ref: str) -> Optional[str]:
    """'p-1', 'P001', 'P-001' -> 'P-001'. Returns None if it isn't ID-shaped."""
    match = _ID_RE.match(ref.strip())
    return format_id(int(match.group(1))) if match else None


# Words that show the user actually talked about status. "new" is deliberately missing:
# "new project ..." must not turn into status=planned.
_STATUS_WORDS = sorted(
    ({"status", "on_hold", "hold"} | set(STATUSES) | set(_STATUS_SYNONYMS)) - {"new"},
    key=len,
    reverse=True,
)
_STATUS_RE = re.compile(
    r"\b(" + "|".join(re.escape(w).replace(r"\ ", r"[\s_-]+") for w in _STATUS_WORDS) + r")\b",
    re.IGNORECASE,
)


def mentions_status(text: str) -> bool:
    """True if the user's own words mention a status (so the LLM didn't invent one)."""
    return bool(_STATUS_RE.search(text))


_MONTHS = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec"
).split()
_WEEKDAYS = (
    "monday tuesday wednesday thursday friday saturday sunday "
    "mon tue tues wed thu thur thurs fri sat sun"
).split()
_RELATIVE = (
    "today tomorrow tonight yesterday next week weeks weekend weekends month months year years "
    "now asap immediately date day days fortnight"
).split()
_ORDINALS = (
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth "
    "thirtieth"
).split()
_DATE_RE = re.compile(
    r"\d|\b(" + "|".join(_MONTHS + _WEEKDAYS + _RELATIVE + _ORDINALS) + r")\b",
    re.IGNORECASE,
)


def mentions_date(text: str) -> bool:
    """True if the user's own words could contain a date (so the LLM didn't invent one).

    Deliberately generous: any digit counts, so a real date is never thrown away.
    """
    return bool(_DATE_RE.search(text))


def normalize_status(value: str) -> Optional[str]:
    key = value.strip().lower()
    if key.replace(" ", "_") in STATUSES:
        return key.replace(" ", "_")
    return _STATUS_SYNONYMS.get(key)


# Characters that sometimes leak from the prompt's JSON into LLM values ('Dresswell},').
# A trailing '.' is NOT stripped: it is legitimate in names like 'Siam Retail Co.'.
_JUNK_CHARS = ' \t\r\n"`{}[],;'


def tidy_value(value: str) -> str:
    """Strip stray quotes/braces/commas from both ends of an LLM-provided value."""
    value = value.strip(_JUNK_CHARS)
    if len(value) >= 2 and value[0] == value[-1] == "'":  # 'Alpha' -> Alpha (keeps Macy's)
        value = value[1:-1].strip(_JUNK_CHARS)
    return value


def clean_fields(raw: dict) -> tuple[dict, list[str]]:
    """Strip/validate field values. Returns (clean_values, problem_messages).

    Invalid optional values are dropped with a friendly explanation rather than
    failing the whole request.
    """
    clean: dict = {}
    problems: list[str] = []
    for name in ALL_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        value = tidy_value(str(value))
        if not value or value.lower() in ("null", "none"):
            continue
        if name == "start_date":
            try:
                value = date.fromisoformat(value).isoformat()
            except ValueError:
                problems.append(
                    f"I couldn't read '{value}' as a date (expected YYYY-MM-DD), "
                    "so I left the start date blank."
                )
                continue
        elif name == "status":
            status = normalize_status(value)
            if status is None:
                problems.append(
                    f"'{value}' isn't a known status ({', '.join(STATUSES)}), "
                    "so I left the status blank."
                )
                continue
            value = status
        clean[name] = value
    return clean, problems


def missing_required(draft: dict) -> list[str]:
    return [name for name in REQUIRED_FIELDS if not draft.get(name)]
