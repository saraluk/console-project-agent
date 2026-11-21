"""Ambiguous names must be asked about, and corrections must remove the wrong field."""
import pytest

from fakes import P


# ----------------------------------------------------------------- corrections
def test_correction_clears_wrong_field(bot, parser, repo):
    """The reported bug: 'Dresswell is not the project name, it's the customer'."""
    parser.script.update(
        {
            "new project Dresswell": P("create", project_name="Dresswell"),
            "Dresswell is not the project name, it's the customer": P(
                "provide_info", clear_fields=["project_name"], customer="Dresswell"
            ),
            "Summer Lookbook": P("provide_info", project_name="Summer Lookbook"),
        }
    )
    bot.handle("new project Dresswell")
    reply = bot.handle("Dresswell is not the project name, it's the customer")

    assert 'Removed project name "Dresswell"' in reply
    assert "What's the project name?" in reply
    assert bot.state["draft"] == {"customer": "Dresswell"}
    assert repo.list_all() == []

    assert bot.handle("Summer Lookbook") == (
        'Done. Created project "Summer Lookbook" for customer Dresswell.'
    )
    [p] = repo.list_all()
    assert (p.project_name, p.customer) == ("Summer Lookbook", "Dresswell")


def test_safety_net_when_llm_forgets_to_clear(bot, parser, repo):
    """Even if the LLM only sets customer, name == customer must not be saved."""
    parser.script.update(
        {
            "new project Dresswell": P("create", project_name="Dresswell"),
            "Dresswell is not the project name, it's the customer": P(
                "provide_info", customer="Dresswell"  # no clear_fields!
            ),
        }
    )
    bot.handle("new project Dresswell")
    reply = bot.handle("Dresswell is not the project name, it's the customer")

    assert 'Is "Dresswell" the project name or the customer?' in reply
    assert repo.list_all() == []
    assert bot.state["awaiting"] == "clarify_field"

    reply = bot.handle("customer")  # answered without the LLM
    assert "What's the project name?" in reply
    assert bot.state["draft"] == {"customer": "Dresswell"}


def test_clear_optional_field(bot, parser):
    parser.script.update(
        {
            "new project Apollo in Bangkok": P("create", project_name="Apollo", location="Bangkok"),
            "actually remove the location": P("provide_info", clear_fields=["location"]),
        }
    )
    bot.handle("new project Apollo in Bangkok")
    reply = bot.handle("actually remove the location")
    assert 'Removed location "Bangkok"' in reply
    assert bot.state["draft"] == {"project_name": "Apollo"}


def test_replacing_a_value_does_not_say_removed(bot, parser):
    parser.script.update(
        {
            "new project Apollo": P("create", project_name="Apollo"),
            "no, call it Zeus": P(
                "provide_info", clear_fields=["project_name"], project_name="Zeus"
            ),
        }
    )
    bot.handle("new project Apollo")
    reply = bot.handle("no, call it Zeus")
    assert "Removed" not in reply
    assert bot.state["draft"] == {"project_name": "Zeus"}


# ------------------------------------------------------------------- ambiguity
def _start_ambiguous(bot, parser):
    parser.script.update(
        {
            "I need a new project": P("create"),
            "Dresswell": P("provide_info", ambiguous_value="Dresswell"),
        }
    )
    bot.handle("I need a new project")
    return bot.handle("Dresswell")


def test_ambiguous_value_asks_instead_of_guessing(bot, parser, repo):
    reply = _start_ambiguous(bot, parser)
    assert 'Is "Dresswell" the project name or the customer?' in reply
    assert bot.state["draft"] == {}
    assert repo.list_all() == []


def test_ambiguous_answered_customer(bot, parser):
    _start_ambiguous(bot, parser)
    calls_before = len(parser.calls)
    reply = bot.handle("it's the customer")
    assert len(parser.calls) == calls_before  # no LLM call needed
    assert "What's the project name?" in reply
    assert bot.state["draft"] == {"customer": "Dresswell"}


def test_ambiguous_answered_project_name(bot, parser):
    _start_ambiguous(bot, parser)
    assert "Who is the customer?" in bot.handle("project name")
    assert bot.state["draft"] == {"project_name": "Dresswell"}


def test_ambiguous_answered_both_saves(bot, parser, repo):
    _start_ambiguous(bot, parser)
    assert bot.handle("both").startswith('Done. Created project "Dresswell"')
    [p] = repo.list_all()
    assert p.project_name == p.customer == "Dresswell"


def test_ambiguous_answered_in_free_text_via_llm(bot, parser):
    _start_ambiguous(bot, parser)
    parser.script["Dresswell is who we're doing it for"] = P("provide_info", customer="Dresswell")
    reply = bot.handle("Dresswell is who we're doing it for")
    assert "What's the project name?" in reply
    assert 'whether "Dresswell" is the project name' in parser.calls[-1][1]  # LLM got context


def test_ambiguous_on_first_message_without_draft(bot, parser):
    parser.script["Dresswell"] = P("provide_info", ambiguous_value="Dresswell")
    reply = bot.handle("Dresswell")
    assert 'Is "Dresswell" the project name or the customer?' in reply
    assert bot.handle("customer").endswith("What's the project name?")


def test_moving_on_sets_value_aside_but_keeps_draft(bot, parser):
    parser.script.update(
        {
            "new project in Bangkok": P("create", location="Bangkok"),
            "Dresswell": P("provide_info", ambiguous_value="Dresswell"),
        }
    )
    bot.handle("new project in Bangkok")
    bot.handle("Dresswell")
    reply = bot.handle("list")
    assert 'set "Dresswell" aside' in reply and "You don't have any projects yet" in reply
    assert bot.state["draft"] == {"location": "Bangkok"}
    assert bot.state["awaiting"] == "fields"


def test_picking_field_removes_stale_copy(bot, parser, repo):
    """Draft already had name=Dresswell; LLM flags a new 'Dresswell' as ambiguous."""
    parser.script.update(
        {
            "new project Dresswell": P("create", project_name="Dresswell"),
            "hmm, Dresswell": P("provide_info", ambiguous_value="Dresswell"),
        }
    )
    bot.handle("new project Dresswell")
    bot.handle("hmm, Dresswell")
    reply = bot.handle("customer")
    assert "What's the project name?" in reply  # no endless re-asking
    assert bot.state["draft"] == {"customer": "Dresswell"}


# ------------------------------------------- the LLM guesses a bare name anyway
def test_bare_name_guessed_by_llm_is_still_asked(bot, parser, repo):
    """Live gpt-4o-mini put a bare 'Dresswell' into project_name (and echoed the draft)
    while both required fields were missing. The app must ask instead."""
    parser.script.update(
        {
            "Start a new project in Bangkok": P("create", location="Bangkok"),
            "Dresswell": P("provide_info", project_name="Dresswell", location="Bangkok"),
        }
    )
    bot.handle("Start a new project in Bangkok")
    reply = bot.handle("Dresswell")
    assert 'Is "Dresswell" the project name or the customer?' in reply
    assert bot.state["draft"] == {"location": "Bangkok"}
    assert bot.handle("customer").endswith("What's the project name?")


def test_bare_name_guess_on_first_message_is_asked(bot, parser):
    parser.script["Dresswell."] = P("create", customer="Dresswell")
    assert 'Is "Dresswell" the project name' in bot.handle("Dresswell.")


def test_bare_name_when_only_one_field_missing_is_not_ambiguous(bot, parser, repo):
    parser.script.update(
        {
            "new project Apollo": P("create", project_name="Apollo"),
            "Dresswell": P("provide_info", customer="Dresswell"),
        }
    )
    bot.handle("new project Apollo")
    assert bot.handle("Dresswell") == 'Done. Created project "Apollo" for customer Dresswell.'


def test_name_with_context_words_is_not_forced_ambiguous(bot, parser):
    parser.script.update(
        {
            "Start a new project in Bangkok": P("create", location="Bangkok"),
            "it's called Dresswell": P("provide_info", project_name="Dresswell"),
        }
    )
    bot.handle("Start a new project in Bangkok")
    assert bot.handle("it's called Dresswell").endswith("Who is the customer?")


def test_stray_characters_from_llm_are_stripped(bot, parser, repo):
    """Live gpt-4o-mini once returned customer 'Dresswell},'."""
    parser.script.update(
        {
            "new project Dresswell": P("create", project_name="Dresswell"),
            "Dresswell is not the project name, it's the customer": P(
                "provide_info", clear_fields=["project_name"], customer="Dresswell},"
            ),
            "Summer Lookbook": P("provide_info", project_name='"Summer Lookbook"'),
        }
    )
    bot.handle("new project Dresswell")
    bot.handle("Dresswell is not the project name, it's the customer")
    assert bot.state["draft"] == {"customer": "Dresswell"}
    bot.handle("Summer Lookbook")
    [p] = repo.list_all()
    assert (p.project_name, p.customer) == ("Summer Lookbook", "Dresswell")


# ------------------------------------------------- invented status is dropped
def test_invented_status_is_dropped(bot, parser, repo):
    """Live gpt-4o-mini added status 'planned' although the user never said it."""
    parser.script["new project Apollo for Acme starting Dec 3"] = P(
        "create", project_name="Apollo", customer="Acme", start_date="2026-12-03", status="planned"
    )
    reply = bot.handle("new project Apollo for Acme starting Dec 3")
    assert reply == 'Done. Created project "Apollo" for customer Acme (start: 2026-12-03).'
    assert repo.get("P-001").status is None


def test_status_kept_when_user_says_it(bot, parser, repo):
    parser.script.update(
        {
            "Apollo for Acme, it's in progress": P(
                "create", project_name="Apollo", customer="Acme", status="active"
            ),
            "mark Apollo as on hold": P("update", project_ref="Apollo", status="on_hold"),
            "set Apollo status to done": P("update", project_ref="Apollo", status="completed"),
        }
    )
    bot.handle("Apollo for Acme, it's in progress")
    assert repo.get("P-001").status == "active"
    bot.handle("mark Apollo as on hold")
    assert repo.get("P-001").status == "on_hold"
    bot.handle("set Apollo status to done")
    assert repo.get("P-001").status == "completed"


def test_mentions_status_words():
    from project_agent.models import mentions_status

    assert mentions_status("it's IN PROGRESS")
    assert mentions_status("put it on-hold")
    assert mentions_status("status?")
    assert not mentions_status("new project Apollo for Acme starting Dec 3")
    assert not mentions_status("we plan to start in Bangkok")


# --------------------------------------------- invented start date is dropped
def test_invented_start_date_is_dropped(bot, parser, repo):
    """Live gpt-4o-mini set start_date to today although the user gave no date."""
    parser.script["create a project called Alpha for customer Acme"] = P(
        "create", project_name="Alpha", customer="Acme", start_date="2026-11-21"
    )
    reply = bot.handle("create a project called Alpha for customer Acme")
    assert reply == 'Done. Created project "Alpha" for customer Acme.'
    assert repo.get("P-001").start_date is None


@pytest.mark.parametrize(
    "text",
    [
        "Alpha for Acme starting Dec 3",
        "Alpha for Acme, starts tomorrow",
        "Alpha for Acme from next Monday",
        "Alpha for Acme on 2026-12-01",
        "Alpha for Acme, kick-off on the fifteenth",
        "Alpha for Acme starting in two weeks",
        "Alpha for Acme, start in a few months",
    ],
)
def test_start_date_kept_when_user_gives_one(bot, parser, repo, text):
    parser.script[text] = P("create", project_name="Alpha", customer="Acme", start_date="2026-12-03")
    bot.handle(text)
    assert repo.get("P-001").start_date == "2026-12-03"


def test_mentions_date_words():
    from project_agent.models import mentions_date

    assert mentions_date("starting DECEMBER 1st")
    assert mentions_date("next week")
    assert mentions_date("on Fri")
    assert not mentions_date("create a project called Alpha for customer Acme")
    assert not mentions_date("Start a new project in Bangkok, it's active")
    assert not mentions_date("Monitoring setup for Saturnine Ltd")  # 'mon'/'sat' need whole words
