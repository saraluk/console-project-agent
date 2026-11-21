import pytest
from fakes import P

from project_agent.cli import run


@pytest.fixture
def seeded(repo):
    repo.add({"project_name": "Website Redesign", "customer": "Acme"})
    repo.add({"project_name": "Website Redesign", "customer": "Globex"})
    repo.add({"project_name": "Mobile App", "customer": "Initech", "status": "active"})
    return repo


# ------------------------------------------------------------------ list / get
def test_list_empty(bot):
    assert bot.handle("list").startswith("You don't have any projects yet.")


def test_list_projects(bot, seeded):
    assert bot.handle("list projects") == (
        "Here are your projects (3):\n"
        "1. Website Redesign — customer: Acme\n"
        "2. Website Redesign — customer: Globex\n"
        "3. Mobile App — customer: Initech · status: active"
    )


def test_get_by_name(bot, parser, seeded):
    parser.script["show mobile app"] = P("get", project_ref="mobile app")
    assert bot.handle("show mobile app") == (
        'Project "Mobile App" — customer: Initech\nStatus: active'
    )


def test_get_not_found(bot, parser, seeded):
    parser.script["show Zeus"] = P("get", project_ref="Zeus")
    assert 'couldn\'t find a project matching "Zeus"' in bot.handle("show Zeus")


def test_get_without_reference(bot, parser, seeded):
    parser.script["show a project"] = P("get")
    assert "Which project do you want to get?" in bot.handle("show a project")


# ---------------------------------------------------------------------- update
def test_update_single_match(bot, parser, seeded):
    parser.script["set Mobile App status to done"] = P(
        "update", project_ref="Mobile App", status="done"
    )
    reply = bot.handle("set Mobile App status to done")
    assert reply == 'Done. Updated project "Mobile App": status → completed.'
    assert seeded.get("P-003").status == "completed"


def test_update_ambiguous_then_choose(bot, parser, seeded):
    parser.script["move Website Redesign to Chiang Mai"] = P(
        "update", project_ref="Website Redesign", location="Chiang Mai"
    )
    reply = bot.handle("move Website Redesign to Chiang Mai")
    assert "found 2 projects" in reply
    assert "1. Website Redesign — customer: Acme\n2. Website Redesign — customer: Globex" in reply
    assert "P-00" not in reply
    assert bot.state["awaiting"] == "which_project"

    reply = bot.handle("2")  # answered without calling the LLM
    assert reply == 'Done. Updated project "Website Redesign": location → Chiang Mai.'
    assert seeded.get("P-002").location == "Chiang Mai"
    assert seeded.get("P-001").location is None


def test_choose_invalid_number_reasks(bot, parser, seeded):
    parser.script["show Website Redesign"] = P("get", project_ref="Website Redesign")
    parser.script["the fifth one"] = P("choose", choice="5")
    bot.handle("show Website Redesign")
    assert "number from 1 to 2" in bot.handle("the fifth one")
    assert bot.state["awaiting"] == "which_project"


def test_new_command_abandons_which_question(bot, parser, seeded):
    parser.script["show Website Redesign"] = P("get", project_ref="Website Redesign")
    bot.handle("show Website Redesign")
    bot.handle("list")
    assert bot.state["awaiting"] is None and bot.state["pending_op"] is None


def test_update_without_changes(bot, parser, seeded):
    parser.script["update Mobile App"] = P("update", project_ref="Mobile App")
    assert 'What would you like to change on "Mobile App"?' in bot.handle("update Mobile App")


# ---------------------------------------------------------------------- delete
def test_delete_requires_explicit_yes(bot, parser, seeded):
    parser.script["delete Mobile App"] = P("delete", project_ref="Mobile App")
    reply = bot.handle("delete Mobile App")
    assert reply == (
        'Delete project "Mobile App" (customer: Initech)? '
        'This cannot be undone. Type "yes" or "no".'
    )
    assert seeded.get("P-003") is not None  # nothing deleted yet

    assert bot.handle("yes") == 'Done. Deleted project "Mobile App".'
    assert seeded.get("P-003") is None


def test_delete_no_keeps_project(bot, parser, seeded):
    parser.script["delete P-003"] = P("delete", project_ref="P-003")
    bot.handle("delete P-003")
    assert bot.handle("no") == 'OK, I kept project "Mobile App". Nothing was deleted.'
    assert seeded.get("P-003") is not None


def test_delete_anything_else_cancels_and_runs_new_command(bot, parser, seeded):
    parser.script["delete P-003"] = P("delete", project_ref="P-003")
    bot.handle("delete P-003")
    reply = bot.handle("list")
    assert 'did not delete project "Mobile App"' in reply and "Here are your projects (3)" in reply
    assert seeded.get("P-003") is not None
    # A later "yes" must not delete anything.
    bot.handle("yes")
    assert seeded.get("P-003") is not None


def test_delete_ambiguous_choose_then_confirm(bot, parser, seeded):
    parser.script["delete Website Redesign"] = P("delete", project_ref="Website Redesign")
    bot.handle("delete Website Redesign")
    assert "cannot be undone" in bot.handle("P-001")
    assert seeded.get("P-001") is not None
    bot.handle("y")
    assert seeded.get("P-001") is None and seeded.get("P-002") is not None


def test_delete_mid_draft_then_reminder(bot, parser, seeded):
    parser.script["new project Apollo"] = P("create", project_name="Apollo")
    parser.script["delete P-003"] = P("delete", project_ref="P-003")
    bot.handle("new project Apollo")
    bot.handle("delete P-003")
    reply = bot.handle("yes")
    assert 'Deleted project "Mobile App"' in reply and 'unfinished project "Apollo"' in reply


# ----------------------------------------------------------------- misc / CLI
def test_unclear_and_help(bot):
    assert "didn't understand" in bot.handle("asdfgh")
    assert "Required for a new project" in bot.handle("help")


def test_choose_without_question_is_unclear(bot, parser):
    parser.script["the first one"] = P("choose", choice="1")
    assert "didn't understand" in bot.handle("the first one")


def _drive(lines, assistant):
    out, feed = [], iter(lines)

    def fake_input(_prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    run(assistant, input_fn=fake_input, output_fn=out.append)
    return out


def test_cli_quit_and_blank_lines(bot):
    out = _drive(["", "   ", "list", "QUIT", "never reached"], bot)
    assert out[-1] == "Goodbye!" and any("don't have any projects yet" in o for o in out)


def test_cli_survives_unexpected_errors():
    class Broken:
        def handle(self, text):
            raise RuntimeError("boom")

    out = _drive(["hello", "exit"], Broken())
    assert "something went wrong: RuntimeError" in out[1] and out[-1] == "Goodbye!"


def test_cli_eof_exits_cleanly(bot):
    assert _drive([], bot)[-1].strip() == "Goodbye!"
