"""Live check: send a few sample sentences to OpenRouter and print how they are parsed.

Usage:  python scripts/check_llm.py      (needs OPENROUTER_API_KEY in .env; costs a fraction of a cent)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from project_agent.config import ConfigError, load_settings  # noqa: E402
from project_agent.llm import LLMParser, LLMUnavailableError, build_chat_model  # noqa: E402

SAMPLES = [
    ("Create a project called Website Redesign for Acme Corp starting next Monday in Bangkok",
     "- No pending question."),
    ("new project for the Bangkok office", "- No pending question."),
    ("Siam Corp",
     '- Project draft in progress: {"project_name": "Office Fit-out"}\n'
     "- The assistant just asked the user for: customer"),
    ("Dresswell",  # should be ambiguous_value, not a guess
     '- Project draft in progress: {"location": "Bangkok"}\n'
     "- The assistant just asked the user for: project name and customer"),
    ("Dresswell is not the project name, it's the customer",  # should clear project_name
     '- Project draft in progress: {"project_name": "Dresswell"}\n'
     "- The assistant just asked the user for: customer"),
    ("clear start date of Dresswell", "- No pending question."),
    ("new project Gamma for Initech starting next Monday", "- No pending question."),  # update, not a new draft
    ("mark Website Redesign as in progress", "- No pending question."),
    ("what's the weather like?", "- No pending question."),
]


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc)
        return 1
    print(f"Model: {settings.model} via {settings.base_url}\n")
    parser = LLMParser(build_chat_model(settings))
    for text, context in SAMPLES:
        try:
            parsed = parser.parse(text, context)
        except LLMUnavailableError as exc:
            print(f"ERROR: {exc}")
            return 1
        fields = {k: v for k, v in parsed.fields.model_dump().items() if v}
        print(
            f"> {text}\n  intent={parsed.intent} ref={parsed.project_ref} fields={fields} "
            f"clear={parsed.clear_fields} ambiguous={parsed.ambiguous_value} "
            f"date_words={parsed.start_date_text}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
