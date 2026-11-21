from project_agent.formatting import (
    created_message,
    project_detail,
    project_line,
    project_list,
    updated_message,
)
from project_agent.models import Project

NOW = "2026-11-21T00:00:00+00:00"


def make(**kw):
    base = {"id": "P-001", "project_name": "Alpha", "customer": "Acme",
            "created_at": NOW, "updated_at": NOW}
    return Project(**{**base, **kw})


def test_created_message_matches_style():
    assert created_message(make()) == 'Done. Created project "Alpha" for customer Acme.'


def test_created_message_with_optional_fields():
    p = make(status="active", start_date="2026-12-01", location="Bangkok")
    assert created_message(p) == (
        'Done. Created project "Alpha" for customer Acme '
        "(status: active, start: 2026-12-01, location: Bangkok)."
    )


def test_list_matches_style():
    projects = [make(), make(id="P-002", project_name="Beta", customer="Globex")]
    assert project_list(projects) == (
        "Here are your projects (2):\n1. Alpha — customer: Acme\n2. Beta — customer: Globex"
    )


def test_list_includes_only_set_optional_fields():
    assert project_line(make(location="Bangkok")) == "Alpha — customer: Acme · location: Bangkok"


def test_long_notes_shortened_in_list_but_full_in_detail():
    notes = "Kick-off with the client's marketing team, then weekly check-ins every Monday morning"
    p = make(notes=notes)
    line = project_line(p)
    assert line.endswith("…") and len(line.split("notes: ")[1]) == 60
    assert project_detail(p).endswith(f"Notes: {notes}")


def test_detail_without_optional_fields_is_one_line():
    assert project_detail(make()) == 'Project "Alpha" — customer: Acme'


def test_ids_never_shown():
    p = make(status="planned")
    for text in (created_message(p), project_line(p), project_detail(p), project_list([p])):
        assert "P-001" not in text


def test_empty_list_message():
    assert project_list([]).startswith("You don't have any projects yet.")


def test_updated_message():
    assert updated_message("Beta", {"location": "Chiang Mai", "status": "active"}) == (
        'Done. Updated project "Beta": location → Chiang Mai, status → active.'
    )
