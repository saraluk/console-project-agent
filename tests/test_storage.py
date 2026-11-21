import json

import pytest

from project_agent.models import clean_fields, normalize_id
from project_agent.storage import ProjectRepository, StorageError


def test_missing_file_starts_empty(repo):
    assert repo.list_all() == []
    assert repo.warning is None


def test_add_persists_and_ids_increment(tmp_path):
    path = tmp_path / "projects.json"
    repo = ProjectRepository(path)
    a = repo.add({"project_name": "Apollo", "customer": "Acme"})
    b = repo.add({"project_name": "Zeus", "customer": "Globex", "status": "active"})
    assert (a.id, b.id) == ("P-001", "P-002")

    reloaded = ProjectRepository(path)
    assert [p.project_name for p in reloaded.list_all()] == ["Apollo", "Zeus"]
    assert json.loads(path.read_text())["next_id"] == 3


def test_ids_not_reused_after_delete(tmp_path):
    path = tmp_path / "projects.json"
    repo = ProjectRepository(path)
    repo.add({"project_name": "A", "customer": "C"})
    repo.add({"project_name": "B", "customer": "C"})
    repo.delete("P-002")
    assert ProjectRepository(path).add({"project_name": "D", "customer": "C"}).id == "P-003"


def test_corrupt_file_is_backed_up(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text("{ not json")
    repo = ProjectRepository(path)
    assert repo.list_all() == []
    assert "unreadable" in repo.warning
    assert list(tmp_path.glob("projects.corrupt-*.bak"))
    assert not path.exists()


def test_empty_file_is_fine(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text("")
    assert ProjectRepository(path).list_all() == []


def test_find_by_id_name_and_partial(repo):
    repo.add({"project_name": "Website Redesign", "customer": "Acme"})
    repo.add({"project_name": "Website Redesign", "customer": "Globex"})
    repo.add({"project_name": "Mobile App", "customer": "Acme"})
    assert [p.id for p in repo.find("p1")] == ["P-001"]
    assert [p.id for p in repo.find("P-003")] == ["P-003"]
    assert [p.id for p in repo.find("website redesign")] == ["P-001", "P-002"]
    assert [p.id for p in repo.find("mobile")] == ["P-003"]
    assert repo.find("nothing") == []


def test_update_and_delete(repo):
    repo.add({"project_name": "Apollo", "customer": "Acme"})
    updated = repo.update("P-001", {"status": "active", "location": "Bangkok"})
    assert (updated.status, updated.location, updated.customer) == ("active", "Bangkok", "Acme")
    assert repo.delete("P-001").project_name == "Apollo"
    assert repo.list_all() == []
    with pytest.raises(KeyError):
        repo.delete("P-001")


def test_failed_write_keeps_memory_unchanged(repo, monkeypatch):
    repo.add({"project_name": "Apollo", "customer": "Acme"})

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("project_agent.storage.os.replace", boom)
    with pytest.raises(StorageError):
        repo.add({"project_name": "Zeus", "customer": "Globex"})
    assert [p.project_name for p in repo.list_all()] == ["Apollo"]


def test_clean_fields_validates_dates_and_status():
    clean, problems = clean_fields(
        {"project_name": "  X ", "start_date": "tomorrow", "status": "in progress", "notes": ""}
    )
    assert clean == {"project_name": "X", "status": "active"}
    assert len(problems) == 1 and "date" in problems[0]

    clean, problems = clean_fields({"status": "weird"})
    assert clean == {} and "status" in problems[0]


def test_normalize_id():
    assert normalize_id("p-7") == "P-007"
    assert normalize_id("P012") == "P-012"
    assert normalize_id("Apollo") is None


def test_tidy_value_strips_leaked_json_but_keeps_real_punctuation():
    from project_agent.models import tidy_value

    assert tidy_value("Dresswell},") == "Dresswell"
    assert tidy_value(' "Alpha" ') == "Alpha"
    assert tidy_value("'Alpha'") == "Alpha"
    assert tidy_value("[Acme]") == "Acme"
    assert tidy_value("Siam Retail Co.") == "Siam Retail Co."
    assert tidy_value("Macy's") == "Macy's"
    assert tidy_value("O'Brien & Sons") == "O'Brien & Sons"
