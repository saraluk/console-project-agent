"""Resolve common relative date phrases in plain code (LLMs miscount weekdays).

Rules (today = the reference date):
- "today" / "tonight" / "now"            -> today
- "tomorrow" / "day after tomorrow"      -> +1 / +2 days
- "<weekday>", "next <weekday>", "coming <weekday>"
                                         -> the next such day AFTER today (never today)
- "this <weekday>"                       -> today if it is that weekday, else the next one
- "in N days|weeks", "N days|weeks from now|today", "in a week"
                                         -> today + N days / weeks
Anything else returns None, and the caller falls back to the LLM's YYYY-MM-DD value.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_LEADING = re.compile(r"^(?:(?:starting|starts|start|from|on|beginning|begins|kick-?off)\s+)+")
_IN_N = re.compile(r"^in\s+(\d+|[a-z]+)\s+(day|days|week|weeks)$")
_N_FROM_NOW = re.compile(r"^(\d+|[a-z]+)\s+(day|days|week|weeks)\s+from\s+(?:now|today)$")


def _amount(word: str) -> Optional[int]:
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word)


def resolve_relative_date(phrase: str, today: date) -> Optional[date]:
    text = re.sub(r"\s+", " ", phrase.strip().casefold().rstrip(".!?,"))
    text = _LEADING.sub("", text).removeprefix("the ").strip()

    if text in ("today", "tonight", "now"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text in ("day after tomorrow", "the day after tomorrow"):
        return today + timedelta(days=2)

    words = text.split()
    if len(words) == 1 and words[0] in _WEEKDAYS:
        return _next_weekday(today, _WEEKDAYS[words[0]], allow_today=False)
    if len(words) == 2 and words[1] in _WEEKDAYS:
        if words[0] in ("next", "coming"):
            return _next_weekday(today, _WEEKDAYS[words[1]], allow_today=False)
        if words[0] == "this":
            return _next_weekday(today, _WEEKDAYS[words[1]], allow_today=True)

    match = _IN_N.match(text) or _N_FROM_NOW.match(text)
    if match:
        amount = _amount(match.group(1))
        if amount is not None:
            days = amount * (7 if match.group(2).startswith("week") else 1)
            return today + timedelta(days=days)
    return None


def _next_weekday(today: date, weekday: int, allow_today: bool) -> date:
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0 and not allow_today:
        ahead = 7
    return today + timedelta(days=ahead)
