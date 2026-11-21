"""Clearing fields of EXISTING projects ("clear start date of <project>")."""

import pytest
from fakes import P


@pytest.fixture
def seeded(repo):
    repo.add({"project_name": "Frank", "customer": "Globex", "start_date": "2026-11-21",
              "location": "Bangkok"})
    repo.add({"project_name": "Apollo", "customer": "Acme"})
    return repo


def test_clear_optional_field_of_existing_project(bot, parser, seeded):
    parser.script["clear start date of Frank"] = P(
        "update", project_ref="Frank", clear_fields=["start_date"]
    )
    reply = bot.handle("clear start date of Frank")
    assert reply == 'Done. Updated project "Frank": cleared start date.'
    frank = seeded.get("P-001")
    assert frank.start_date is None and frank.location == "Bangkok"


def test_reported_bug_misread_as_new_draft(bot, parser, seeded):
    """Live gpt-4o-mini output for 'clear start date of Dresswell'-style input:
    provide_info + customer=<project> + clear_fields. Must NOT start a new project."""
    parser.script["clear start date of Frank"] = P(
        "provide_info", customer="Frank", clear_fields=["start_date"]
    )
    reply = bot.handle("clear start date of Frank")
    assert reply == 'Done. Updated project "Frank": cleared start date.'
    assert "What's the project name?" not in reply
    assert bot.state.get("draft") is None
    assert seeded.get("P-001").customer == "Globex"  # the misplaced value wasn't applied


def test_misread_clear_with_duplicate_names_asks_which(bot, parser, seeded):
    seeded.add({"project_name": "Frank", "customer": "Initech", "start_date": "2026-12-01"})
    parser.script["clear start date of Frank"] = P(
        "provide_info", customer="Frank", clear_fields=["start_date"]
    )
    reply = bot.handle("clear start date of Frank")
    assert "found 2 projects" in reply and "Which one do you want to update?" in reply
    assert bot.handle("2") == 'Done. Updated project "Frank": cleared start date.'
    assert seeded.get("P-003").start_date is None
    assert seeded.get("P-001").start_date == "2026-11-21"


def test_clear_and_set_in_one_message(bot, parser, seeded):
    parser.script["clear Frank's location and mark it active"] = P(
        "update", project_ref="Frank", clear_fields=["location"], status="active"
    )
    reply = bot.handle("clear Frank's location and mark it active")
    assert reply == 'Done. Updated project "Frank": status → active, cleared location.'


def test_clear_already_empty_field(bot, parser, seeded):
    parser.script["clear notes of Apollo"] = P("update", project_ref="Apollo", clear_fields=["notes"])
    assert bot.handle("clear notes of Apollo") == 'Nothing to change: "Apollo" has no notes set.'


def test_required_field_cannot_be_cleared(bot, parser, seeded):
    parser.script["clear customer of Frank"] = P(
        "update", project_ref="Frank", clear_fields=["customer"]
    )
    reply = bot.handle("clear customer of Frank")
    assert "Customer is required, so it can't be cleared" in reply
    assert '"change Frank customer to <new customer>"' in reply
    assert seeded.get("P-001").customer == "Globex"


def test_clear_without_project_and_no_draft_asks_which(bot, parser, seeded):
    parser.script["clear the start date"] = P("provide_info", clear_fields=["start_date"])
    reply = bot.handle("clear the start date")
    assert reply.startswith("Which project do you want to update?")
    assert bot.state.get("draft") is None


def test_clear_naming_project_while_draft_open_updates_project(bot, parser, seeded):
    parser.script.update(
        {
            "new project Zeus in Paris": P("create", project_name="Zeus", location="Paris"),
            "clear location of Frank": P(
                "provide_info", project_ref="Frank", clear_fields=["location"]
            ),
        }
    )
    bot.handle("new project Zeus in Paris")
    reply = bot.handle("clear location of Frank")
    assert 'Done. Updated project "Frank": cleared location.' in reply
    assert 'unfinished project "Zeus"' in reply  # draft untouched, reminder shown
    assert bot.state["draft"] == {"project_name": "Zeus", "location": "Paris"}
    assert seeded.get("P-001").location is None


def test_draft_correction_still_applies_to_draft(bot, parser, seeded):
    """No project named + draft open -> it's a draft correction (earlier fix still works)."""
    parser.script.update(
        {
            "new project Zeus in Paris": P("create", project_name="Zeus", location="Paris"),
            "remove the location": P("provide_info", clear_fields=["location"]),
        }
    )
    bot.handle("new project Zeus in Paris")
    reply = bot.handle("remove the location")
    assert 'Removed location "Paris"' in reply
    assert bot.state["draft"] == {"project_name": "Zeus"}
    assert seeded.get("P-001").location == "Bangkok"
