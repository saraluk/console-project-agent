"""OpenRouter chat model + the parser that turns text into ParsedInput."""

from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Protocol

import openai
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import Settings
from .graph.prompts import build_system_prompt
from .models import ParsedInput

log = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """The model could not be reached (network, auth, rate limit...)."""


class InputParser(Protocol):
    """Anything that can read a user message. The graph only depends on this."""

    def parse(self, text: str, context: str) -> ParsedInput: ...


def build_chat_model(settings: Settings) -> ChatOpenAI:
    # OpenRouter speaks the OpenAI API, so ChatOpenAI works with a different base_url.
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=0,
        timeout=settings.timeout_seconds,
        max_retries=1,
    )


class LLMParser:
    """Uses structured output so the model fills in a ParsedInput form."""

    def __init__(self, chat_model: ChatOpenAI, today: Callable[[], date] = date.today):
        self._runnable = chat_model.with_structured_output(
            ParsedInput,
            method="json_schema",  # explicit: the default differs between versions
            strict=True,
            include_raw=True,  # malformed output comes back as a value, not an exception
        )
        self._today = today

    def parse(self, text: str, context: str) -> ParsedInput:
        messages = [
            SystemMessage(build_system_prompt(self._today())),
            HumanMessage(f"Conversation context:\n{context}\n\nUser message:\n{text}"),
        ]
        last_problem = "unknown error"
        for attempt in (1, 2):
            try:
                result = self._runnable.invoke(messages)
            except openai.AuthenticationError as exc:
                raise LLMUnavailableError(
                    "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env."
                ) from exc
            except openai.NotFoundError as exc:
                raise LLMUnavailableError(
                    "OpenRouter doesn't recognise that model. Check OPENROUTER_MODEL in .env."
                ) from exc
            except (openai.APIError, OSError) as exc:  # timeouts, 5xx, rate limits, network
                last_problem = f"{type(exc).__name__}: {exc}"
                log.debug("LLM call failed (attempt %s): %s", attempt, last_problem)
                continue

            parsed = result.get("parsed")
            if isinstance(parsed, ParsedInput):
                return parsed
            # The model answered but not in the expected shape -> treat as unclear input.
            log.debug("Unparseable LLM output: %s", result.get("parsing_error"))
            return ParsedInput.make("unclear")

        raise LLMUnavailableError(
            "I couldn't reach the language model just now. Please try again in a moment."
        ) from None
