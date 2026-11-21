"""Load settings from the environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "openai/gpt-4o-mini"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str
    projects_file: Path
    timeout_seconds: float = 30.0


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings from `.env` (project root) and the process environment."""
    load_dotenv(env_file or PROJECT_ROOT / ".env")

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key.startswith("your-"):
        raise ConfigError(
            "OPENROUTER_API_KEY is not set.\n"
            "  1. Copy the example file:  cp .env.example .env\n"
            "  2. Put your key from https://openrouter.ai/keys into .env"
        )

    model = os.getenv("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL

    projects_file = Path(os.getenv("PROJECTS_FILE", "").strip() or "projects.json")
    if not projects_file.is_absolute():
        projects_file = PROJECT_ROOT / projects_file

    try:
        timeout = float(os.getenv("OPENROUTER_TIMEOUT", "30"))
    except ValueError as exc:
        raise ConfigError("OPENROUTER_TIMEOUT must be a number of seconds.") from exc

    return Settings(
        api_key=api_key,
        model=model,
        base_url=OPENROUTER_BASE_URL,
        projects_file=projects_file,
        timeout_seconds=timeout,
    )
