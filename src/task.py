"""Translation task — state management with persistence.

Each paper gets one Task stored at data/tasks/{arxiv_id}.json.
Survives crashes: on load, detects if previous run was interrupted.
"""

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum


class State(Enum):
    PENDING = "pending"
    FETCHING = "fetching"
    PARSING = "parsing"
    TRANSLATING = "translating"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"

    @classmethod
    def is_intermediate(cls, s: "State") -> bool:
        """States that mean the task was in-progress when interrupted."""
        return s in (cls.FETCHING, cls.PARSING, cls.TRANSLATING, cls.RENDERING)


@dataclass
class Task:
    arxiv_id: str
    state: State = State.PENDING
    blocks: list[dict] = field(default_factory=list)   # [{idx, hash, done}]
    total: int = 0
    translated: int = 0
    error: str | None = None
    interrupted: bool = False
    error_history: list[dict] = field(default_factory=list)  # [{time, state, error}]
    created_at: float = 0.0
    updated_at: float = 0.0

    _path: str = field(default="", repr=False)

    # ──── computed ────

    @property
    def is_done(self) -> bool:
        return self.state == State.DONE

    @property
    def progress(self) -> str:
        return f"{self.translated}/{self.total}" if self.total else ""

    @property
    def progress_pct(self) -> float:
        return (self.translated / self.total * 100) if self.total > 0 else 0.0

    # ──── state transitions ────

    def set_fetching(self):
        self._transition(State.FETCHING)

    def set_parsing(self):
        self._transition(State.PARSING)

    def set_translating(self):
        self._transition(State.TRANSLATING)

    def set_rendering(self):
        self._transition(State.RENDERING)

    def set_done(self):
        self._transition(State.DONE)

    def set_error(self, msg: str):
        self.error = msg
        self.state = State.FAILED
        self.error_history.append({
            "time": time.time(),
            "state": "failed",
            "error": msg,
        })
        self._touch()
        self._save()

    # ──── block progress ────

    def mark_done(self, idx: int):
        for b in self.blocks:
            if b["idx"] == idx and not b["done"]:
                b["done"] = True
                self.translated += 1
        self._touch()
        self._save()

    # ──── init blocks ────

    def set_blocks(self, hashes: list[str]):
        """Initialize blocks from a list of SHA256 hashes."""
        self.blocks = [{"idx": i, "hash": h, "done": False} for i, h in enumerate(hashes)]
        self.total = len(self.blocks)
        self.translated = 0
        self._touch()
        self._save()

    def pending_indices(self) -> list[int]:
        """Return indices of blocks not yet translated."""
        return [b["idx"] for b in self.blocks if not b["done"]]

    # ──── persistence ────

    @classmethod
    def load(cls, arxiv_id: str, tasks_dir: str) -> "Task":
        path = os.path.join(tasks_dir, f"{arxiv_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["state"] = State(d["state"])
            task = cls(**d)
            task._path = path

            # Detect forced termination
            if State.is_intermediate(task.state):
                task.interrupted = True
                task.error_history.append({
                    "time": time.time(),
                    "state": task.state.value,
                    "error": "Interrupted (forced termination or crash)",
                })
                task.error = f"Interrupted while {task.state.value}"
                task.state = State.FAILED
                task._touch()
                task._save()

            return task

        task = cls(arxiv_id=arxiv_id, created_at=time.time())
        task._path = path
        task._touch()
        task._save()
        return task

    def _transition(self, s: State):
        self.state = s
        self._touch()
        self._save()

    def _touch(self):
        self.updated_at = time.time()

    def _save(self):
        if not self._path:
            return
        d = {
            "arxiv_id": self.arxiv_id,
            "state": self.state.value,
            "blocks": self.blocks,
            "total": self.total,
            "translated": self.translated,
            "error": self.error,
            "interrupted": self.interrupted,
            "error_history": self.error_history[-10:],  # keep last 10
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
