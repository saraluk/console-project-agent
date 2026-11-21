"""Entry point: python main.py"""

from __future__ import annotations

import logging
import os
import sys

from project_agent.agent import ProjectAssistant
from project_agent.cli import run
from project_agent.config import ConfigError, load_settings
from project_agent.llm import LLMParser, build_chat_model
from project_agent.storage import ProjectRepository, StorageError


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.getenv("PROJECT_AGENT_DEBUG") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
        repo = ProjectRepository(settings.projects_file)
    except (ConfigError, StorageError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1

    if repo.warning:
        print(repo.warning)

    parser = LLMParser(build_chat_model(settings))
    run(ProjectAssistant(parser, repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
