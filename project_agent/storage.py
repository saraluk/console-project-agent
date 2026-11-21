"""JSON-file storage for projects."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from .models import Project, format_id, normalize_id


class StorageError(Exception):
    """Raised when projects.json cannot be read or written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectRepository:
    """Loads projects once, keeps them in memory, and saves after every change.

    File format: {"next_id": <int>, "projects": [<Project>, ...]}
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.warning: Optional[str] = None  # set if the file had to be recovered
        self._projects, self._next_id = self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> tuple[list[Project], int]:
        if not self.path.exists():
            return [], 1
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Could not read {self.path}: {exc}") from exc

        if not text.strip():
            return [], 1

        try:
            data = json.loads(text)
            raw_projects = data if isinstance(data, list) else data.get("projects", [])
            projects = [Project.model_validate(item) for item in raw_projects]
            next_id = int(data.get("next_id", 1)) if isinstance(data, dict) else 1
        except (json.JSONDecodeError, ValidationError, AttributeError, TypeError, ValueError):
            backup = self.path.with_name(
                f"{self.path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}.bak"
            )
            try:
                self.path.replace(backup)
            except OSError as exc:
                raise StorageError(
                    f"{self.path} is unreadable and could not be backed up: {exc}"
                ) from exc
            self.warning = (
                f"Warning: {self.path.name} was unreadable. It was moved to "
                f"{backup.name} and a fresh, empty project list was started."
            )
            return [], 1

        highest = max((int(p.id.split("-")[1]) for p in projects), default=0)
        return projects, max(next_id, highest + 1)

    # ------------------------------------------------------------------ save
    def _save(self, projects: list[Project], next_id: int) -> None:
        payload = {
            "next_id": next_id,
            "projects": [p.model_dump() for p in projects],
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)  # atomic swap: never leaves a half-written file
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise StorageError(f"Could not save to {self.path}: {exc}") from exc
        # Only update memory after the file write succeeded.
        self._projects, self._next_id = projects, next_id

    # --------------------------------------------------------------- queries
    def list_all(self) -> list[Project]:
        return list(self._projects)

    def get(self, project_id: str) -> Optional[Project]:
        pid = normalize_id(project_id)
        return next((p for p in self._projects if p.id == pid), None)

    def find(self, ref: str) -> list[Project]:
        """Find by ID, then exact name (case-insensitive), then partial name."""
        ref = ref.strip()
        if not ref:
            return []
        by_id = self.get(ref) if normalize_id(ref) else None
        if by_id:
            return [by_id]
        key = ref.casefold()
        exact = [p for p in self._projects if p.project_name.casefold() == key]
        if exact:
            return exact
        return [p for p in self._projects if key in p.project_name.casefold()]

    def find_exact_name(self, name: str) -> list[Project]:
        key = name.strip().casefold()
        return [p for p in self._projects if p.project_name.casefold() == key]

    # ------------------------------------------------------------- mutations
    def add(self, fields: dict) -> Project:
        now = _now()
        project = Project(id=format_id(self._next_id), created_at=now, updated_at=now, **fields)
        self._save(self._projects + [project], self._next_id + 1)
        return project

    def update(self, project_id: str, changes: dict) -> Project:
        current = self.get(project_id)
        if current is None:
            raise KeyError(project_id)
        updated = Project.model_validate(
            {**current.model_dump(), **changes, "updated_at": _now()}
        )
        projects = [updated if p.id == current.id else p for p in self._projects]
        self._save(projects, self._next_id)
        return updated

    def delete(self, project_id: str) -> Project:
        current = self.get(project_id)
        if current is None:
            raise KeyError(project_id)
        projects = [p for p in self._projects if p.id != current.id]
        self._save(projects, self._next_id)  # IDs are never reused
        return current

    def delete_all(self) -> int:
        """Remove every project. Returns how many were deleted. IDs are never reused."""
        count = len(self._projects)
        self._save([], self._next_id)
        return count
