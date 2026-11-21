"""'delete all projects' with double confirmation: "yes", then the exact phrase."""

import pytest
from fakes import P

from project_agent.storage import ProjectRepository, StorageError


@pytest.fixture
def seeded(repo):
    repo.add({"project_name": "Alpha", "customer": "Acme"})
    repo.add({"project_name": "Beta", "customer": "Globex", "status": "active"})
    return repo


def _first_prompt(bot, text="delete all projects"):
    return bot.handle(text)


def test_full_path_deletes_everything(bot, parser, seeded, tmp_path):
    reply = _first_prompt(bot)
    assert reply == (
        "This will permanently delete ALL 2 projects:\n"
        "1. Alpha — customer: Acme\n"
        "2. Beta — customer: Globex · status: active\n"
        'Are you sure? Type "yes" to continue or "no" to cancel.'
    )
    assert len(seeded.list_all()) == 2

    assert bot.handle("yes") == 'Last check: type "delete all" to confirm. Anything else cancels.'
    assert len(seeded.list_all()) == 2  # still nothing deleted after the first yes

    assert bot.handle("delete all") == "Done. Deleted all 2 projects."
    assert seeded.list_all() == []
    assert ProjectRepository(seeded.path).list_all() == []  # persisted to disk
    assert parser.calls == []  # the whole flow works without the LLM


@pytest.mark.parametrize(
    "phrase", ["delete all", "Clear all projects", "remove all the projects", "clear all."]
)
def test_fixed_phrases_start_the_flow(bot, seeded, phrase):
    assert "permanently delete ALL 2 projects" in bot.handle(phrase)


def test_other_wording_via_llm(bot, parser, seeded):
    parser.script["wipe out every single project"] = P("delete_all")
    assert "permanently delete ALL 2 projects" in bot.handle("wipe out every single project")


def test_plain_clear_does_not_start_delete_all(bot, parser, seeded):
    """Only 'clear all' / 'clear all projects' wipe; a bare 'clear' goes to the LLM as usual."""
    reply = bot.handle("clear")
    assert "permanently delete" not in reply
    assert bot.state.get("awaiting") is None
    assert len(seeded.list_all()) == 2


def test_no_at_first_step_cancels(bot, seeded):
    _first_prompt(bot)
    assert bot.handle("no") == "OK, nothing was deleted."
    assert len(seeded.list_all()) == 2
    assert bot.state["awaiting"] is None


def test_yes_twice_is_not_enough(bot, seeded):
    _first_prompt(bot)
    bot.handle("yes")
    reply = bot.handle("yes")
    assert reply == 'OK, nothing was deleted. (The last step needs the exact words "delete all".)'
    assert len(seeded.list_all()) == 2
    # And a later "delete all" starts over from the first question instead of wiping.
    assert "Are you sure?" in bot.handle("delete all")
    assert len(seeded.list_all()) == 2


def test_wrong_phrase_at_last_step_cancels(bot, parser, seeded):
    _first_prompt(bot)
    bot.handle("yes")
    reply = bot.handle("delete everything")  # not the exact phrase
    assert reply.startswith("OK, nothing was deleted.")
    assert len(seeded.list_all()) == 2


def test_other_command_mid_confirmation_cancels_and_runs(bot, seeded):
    _first_prompt(bot)
    reply = bot.handle("list")
    assert reply.startswith("OK, nothing was deleted.\nHere are your projects (2):")
    assert bot.handle("yes") != "Done. Deleted all 2 projects."  # stray yes does nothing
    assert len(seeded.list_all()) == 2


def test_llm_misreading_single_delete_is_still_safe(bot, parser, seeded):
    parser.script["delete Alpha"] = P("delete_all")  # model wrongly picks delete_all
    reply = bot.handle("delete Alpha")
    assert "ALL 2 projects" in reply  # the count and full list make the mistake obvious
    assert bot.handle("no") == "OK, nothing was deleted."
    assert len(seeded.list_all()) == 2


def test_empty_list(bot):
    assert bot.handle("delete all projects") == "You don't have any projects to delete."
    assert bot.state.get("awaiting") is None


def test_draft_survives_and_is_reminded(bot, parser, seeded):
    parser.script["new project Zeus"] = P("create", project_name="Zeus")
    bot.handle("new project Zeus")
    _first_prompt(bot)
    bot.handle("yes")
    reply = bot.handle("delete all")
    assert reply.startswith("Done. Deleted all 2 projects.")
    assert 'unfinished project "Zeus", missing: customer' in reply
    assert bot.state["draft"] == {"project_name": "Zeus"}


def test_long_list_is_truncated(bot, repo):
    for i in range(12):
        repo.add({"project_name": f"P{i}", "customer": "Acme"})
    reply = bot.handle("delete all projects")
    assert "ALL 12 projects" in reply and "10. P9" in reply and "…and 2 more" in reply
    assert "11." not in reply


def test_storage_failure_deletes_nothing(bot, seeded, monkeypatch):
    def boom(*_a, **_k):
        raise StorageError("Could not save to projects.json: disk full")

    _first_prompt(bot)
    bot.handle("yes")
    monkeypatch.setattr(seeded, "_save", boom)
    reply = bot.handle("delete all")
    assert "disk full" in reply and "Nothing was deleted." in reply
    assert len(seeded.list_all()) == 2


def test_ids_not_reused_after_delete_all(seeded):
    seeded.delete_all()
    assert seeded.add({"project_name": "Gamma", "customer": "Initech"}).id == "P-003"
