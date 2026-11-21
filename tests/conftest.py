import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeParser  # noqa: E402

from project_agent.agent import ProjectAssistant  # noqa: E402
from project_agent.storage import ProjectRepository  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    return ProjectRepository(tmp_path / "projects.json")


@pytest.fixture
def parser():
    return FakeParser()


@pytest.fixture
def bot(parser, repo):
    return ProjectAssistant(parser, repo)
