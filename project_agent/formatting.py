"""Turn projects into readable console text.

Style:
    Done. Created project "Alpha" for customer Acme.
    Here are your projects (2):
    1. Alpha — customer: Acme
    2. Beta — customer: Globex · status: active · start: 2026-12-01

Empty optional fields are always skipped. Internal IDs are never shown.
"""

from __future__ import annotations

from .models import FIELD_LABELS, Project

NOTES_PREVIEW_CHARS = 60

# Short labels for optional fields, in display order.
_OPTIONAL_LABELS = (
    ("status", "status"),
    ("start_date", "start"),
    ("location", "location"),
    ("notes", "notes"),
)


def _shorten(text: str, limit: int = NOTES_PREVIEW_CHARS) -> str:
    text = " ".join(text.split())  # collapse newlines/extra spaces
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _optional_parts(p: Project, short_notes: bool = True, capitalize: bool = False) -> list[str]:
    parts = []
    for field, label in _OPTIONAL_LABELS:
        value = getattr(p, field)
        if not value:
            continue
        if field == "notes" and short_notes:
            value = _shorten(value)
        parts.append(f"{label.capitalize() if capitalize else label}: {value}")
    return parts


def project_line(p: Project) -> str:
    """'Beta — customer: Globex · status: active · start: 2026-12-01'"""
    return " · ".join([f"{p.project_name} — customer: {p.customer}", *_optional_parts(p)])


def numbered(projects: list[Project]) -> str:
    return "\n".join(f"{i}. {project_line(p)}" for i, p in enumerate(projects, 1))


def project_list(projects: list[Project]) -> str:
    if not projects:
        return (
            "You don't have any projects yet. "
            "Try: \"create a project called Alpha for customer Acme\"."
        )
    return f"Here are your projects ({len(projects)}):\n{numbered(projects)}"


def project_detail(p: Project) -> str:
    header = f'Project "{p.project_name}" — customer: {p.customer}'
    extras = _optional_parts(p, short_notes=False, capitalize=True)
    return header + ("\n" + " · ".join(extras) if extras else "")


def created_message(p: Project) -> str:
    extras = _optional_parts(p)
    tail = f" ({', '.join(extras)})" if extras else ""
    return f'Done. Created project "{p.project_name}" for customer {p.customer}{tail}.'


def updated_message(old_name: str, changes: dict) -> str:
    """A value of None means the field was cleared."""
    what = ", ".join(
        f"cleared {FIELD_LABELS.get(k, k)}" if v is None else f"{FIELD_LABELS.get(k, k)} → {v}"
        for k, v in changes.items()
    )
    return f'Done. Updated project "{old_name}": {what}.'


def describe_fields(fields: dict) -> str:
    """{'location': 'Bangkok'} -> 'location: Bangkok'"""
    return ", ".join(f"{FIELD_LABELS.get(k, k)}: {v}" for k, v in fields.items())
