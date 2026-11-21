"""Relative dates are computed in code, not by the LLM."""

from datetime import date

import pytest
from fakes import FakeParser, P

from project_agent.agent import ProjectAssistant
from project_agent.dates import resolve_relative_date

SATURDAY = date(2026, 11, 21)  # the day the "next Monday -> Saturday" bug was seen


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("today", "2026-11-21"),
        ("tomorrow", "2026-11-22"),
        ("the day after tomorrow", "2026-11-23"),
        ("next Monday", "2026-11-23"),  # the coming Monday (the reported bug said 11-28)
        ("Monday", "2026-11-23"),
        ("coming monday", "2026-11-23"),
        ("next mon", "2026-11-23"),
        ("starting next Monday", "2026-11-23"),
        ("on Friday", "2026-11-27"),
        ("Saturday", "2026-11-28"),  # a bare weekday never means today
        ("next Saturday", "2026-11-28"),
        ("this Saturday", "2026-11-21"),  # "this <today's weekday>" = today
        ("this Sunday", "2026-11-22"),
        ("in 3 days", "2026-11-24"),
        ("in a week", "2026-11-28"),
        ("in two weeks", "2026-12-05"),
        ("10 days from now", "2026-12-01"),
    ],
)
def test_resolves_common_phrases(phrase, expected):
    assert resolve_relative_date(phrase, SATURDAY).isoformat() == expected


@pytest.mark.parametrize("phrase", ["Dec 3", "2026-12-01", "next month", "end of March", "someday"])
def test_other_phrases_fall_back_to_llm(phrase):
    assert resolve_relative_date(phrase, SATURDAY) is None


@pytest.fixture
def dated_bot(repo):
    parser = FakeParser()
    return ProjectAssistant(parser, repo, today=lambda: SATURDAY), parser


def test_llm_miscounted_weekday_is_corrected(dated_bot, repo):
    bot, parser = dated_bot
    text = "create Gamma for Initech starting next Monday"
    parser.script[text] = P(  # what gpt-4o-mini actually returned
        "create", project_name="Gamma", customer="Initech", start_date="2026-11-28",
        start_date_text="next Monday",
    )
    assert bot.handle(text) == (
        'Done. Created project "Gamma" for customer Initech (start: 2026-11-23).'
    )


def test_absolute_dates_use_llm_value(dated_bot, repo):
    bot, parser = dated_bot
    text = "create Delta for Umbrella, kick-off Dec 3"
    parser.script[text] = P(
        "create", project_name="Delta", customer="Umbrella", start_date="2026-12-03",
        start_date_text="Dec 3",
    )
    bot.handle(text)
    assert repo.get("P-001").start_date == "2026-12-03"


def test_date_words_not_in_message_are_ignored(dated_bot, repo):
    """If the model 'quotes' words the user never typed, don't trust them."""
    bot, parser = dated_bot
    text = "create Zeta for Acme on the 30th"
    parser.script[text] = P(
        "create", project_name="Zeta", customer="Acme", start_date="2026-11-30",
        start_date_text="tomorrow",
    )
    bot.handle(text)
    assert repo.get("P-001").start_date == "2026-11-30"


def test_update_with_relative_date(dated_bot, repo):
    bot, parser = dated_bot
    repo.add({"project_name": "Gamma", "customer": "Initech"})
    text = "move Gamma's start to this Sunday"
    parser.script[text] = P(
        "update", project_ref="Gamma", start_date="2026-11-29", start_date_text="this Sunday"
    )
    assert bot.handle(text) == 'Done. Updated project "Gamma": start date → 2026-11-22.'
