"""Per-paper `pi` process registry with idle eviction, plus session indexing.

One pi process per paper (not one per browser tab, and not one global process):
paper contexts stay isolated, a crash only affects its own paper, and lazy
spawning is cheap because `pi --mode rpc` starts in well under a second.

Sessions persist on disk under `data/papers/{arxiv_id}/chat/sessions/`. Because pi only
writes a session file once a turn actually produces an assistant message, the
directory is also our conversation history — which is what the UI's conversation
list is built from.

Resuming is explicit rather than relying on pi's `--continue`: we pass
`--session <path>` ourselves. That behaves predictably (verified: it restores the
full message list) and lets the UI open *any* past conversation, not just the
most recent one.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .. import config
from .bridge import PiBridge, PiBridgeError
from .context import workspace_dir


# --------------------------------------------------------------------------- #
# session index (the conversation list)
# --------------------------------------------------------------------------- #

def sessions_dir(arxiv_id: str) -> Path:
    return Path(config.chat_sessions_dir(arxiv_id))


def list_sessions(arxiv_id: str) -> list[dict]:
    """List this paper's saved conversations, newest first.

    Each entry: ``{id, path, created, messages, title, name, bytes}``.
    ``title`` falls back to the first user message when the session has not been
    named (`/name` / `set_session_name`).
    A malformed file is skipped rather than breaking the list.
    """
    d = sessions_dir(arxiv_id)
    if not d.exists():
        return []

    out: list[dict] = []
    for f in d.glob("*.jsonl"):
        try:
            title = ""
            name = ""
            created = ""
            count = 0
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # torn tail — count what we could read
                    kind = rec.get("type")
                    if kind == "session":
                        created = rec.get("timestamp", "")
                    elif kind in ("session_info", "session_name"):
                        # Written by `--name`, `/name` and set_session_name.
                        if rec.get("name"):
                            name = str(rec["name"])
                    elif kind == "message":
                        m = rec.get("message") or {}
                        if m.get("role") == "user" and not title:
                            title = _first_text(m.get("content"))
                        count += 1
            out.append({
                "id": f.stem.split("_")[-1],
                "path": str(f),
                "created": created,
                "messages": count,
                "name": name,
                "title": name or title or "(空会话)",
                "bytes": f.stat().st_size,
            })
        except OSError:
            continue
    out.sort(key=lambda s: s["created"] or "", reverse=True)
    return out


def resolve_session(arxiv_id: str, session: str) -> str | None:
    """Map a session id / path / bare filename to a path inside this paper."""
    session = (session or "").strip()
    if not session:
        return None
    for s in list_sessions(arxiv_id):
        if s["id"] == session:
            return s["path"]
    d = sessions_dir(arxiv_id).resolve()
    cand = Path(session)
    if not cand.is_absolute():
        cand = d / session
    try:
        cand = cand.resolve()
        # Only ever operate inside this paper's session directory.
        if cand.parent == d and cand.suffix == ".jsonl" and cand.exists():
            return str(cand)
    except OSError:
        pass
    return None


def delete_session(arxiv_id: str, session: str,
                   allow_permanent: bool = False) -> dict:
    """Delete one saved conversation.

    pi has no delete RPC (in the TUI it lives behind `/resume` + Ctrl+D), and
    like pi we prefer the system `trash` so a mis-click is recoverable.

    Two safety properties, both learned the hard way:

    * The *active* session cannot be unlinked underneath pi — it holds the file
      open and would append into a deleted path, recreating it half-written.
      Reported as ``active: True`` so the caller can switch away and retry.
    * If ``trash`` is unavailable or fails, we **do not** silently fall back to
      ``unlink()``. A "delete" that the UI describes as recoverable must not be
      an unrecoverable erase, so permanent deletion needs ``allow_permanent``.
    """
    path = resolve_session(arxiv_id, session)
    if not path:
        return {"ok": False, "error": f"unknown session: {session}"}

    active = None
    with registry._lock:
        b = registry._bridges.get(arxiv_id)
        if b is not None:
            active = b.session_path
    if active and Path(active).resolve() == Path(path).resolve():
        return {"ok": False, "active": True, "path": path,
                "error": "这个会话正在使用中"}

    try:
        trashed, why = _trash(path)
        if trashed:
            return {"ok": True, "path": path, "trashed": True}
        if not allow_permanent:
            return {"ok": False, "path": path, "trash_failed": True,
                    "error": f"无法移入废纸篓（{why}）；需要显式确认才能永久删除"}
        Path(path).unlink()
        return {"ok": True, "path": path, "trashed": False, "permanent": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def _trash(path: str) -> tuple[bool, str]:
    """Move to the OS trash. Returns ``(ok, reason)``."""
    import shutil as _shutil
    import subprocess
    exe = _shutil.which("trash")
    if not exe:
        return False, "没有 trash 命令"
    try:
        r = subprocess.run([exe, path], capture_output=True, timeout=20)
        if r.returncode == 0:
            return True, ""
        msg = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (msg[-1][:120] if msg else f"exit {r.returncode}")
    except Exception as e:
        return False, str(e)[:120]


def latest_session(arxiv_id: str) -> str | None:
    """Path of the most recent conversation, or None if there is none."""
    s = list_sessions(arxiv_id)
    return s[0]["path"] if s else None


def _first_text(content) -> str:
    if isinstance(content, str):
        return " ".join(content.split())[:80]
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                return " ".join((c.get("text") or "").split())[:80]
    return ""


# --------------------------------------------------------------------------- #
# process registry
# --------------------------------------------------------------------------- #

class PiSessionRegistry:
    """Owns the lifetime of every pi process the server is talking to."""

    def __init__(self, idle_timeout: int | None = None, reaper_interval: float = 60.0):
        self.idle_timeout = config.CHAT_IDLE_TIMEOUT if idle_timeout is None else idle_timeout
        self.reaper_interval = reaper_interval
        self._bridges: dict[str, PiBridge] = {}
        self._lock = threading.RLock()
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def start_reaper(self) -> None:
        """Background thread that stops idle pi processes."""
        if self._reaper is not None:
            return
        self._reaper = threading.Thread(
            target=self._reap_loop, name="pi-reaper", daemon=True
        )
        self._reaper.start()

    def _reap_loop(self) -> None:
        while not self._stop.wait(self.reaper_interval):
            try:
                self.reap_idle()
            except Exception:
                pass

    def reap_idle(self) -> list[str]:
        """Stop processes that have been idle beyond the timeout. Returns ids."""
        now = time.monotonic()
        stopped: list[str] = []
        with self._lock:
            for arxiv_id, b in list(self._bridges.items()):
                idle = now - b.last_active
                # Never evict mid-turn or while a client is watching: the
                # subscription is what keeps the event stream alive.
                if idle < self.idle_timeout or b._subscribers:
                    continue
                b.stop()
                del self._bridges[arxiv_id]
                stopped.append(arxiv_id)
        return stopped

    def stop_all(self) -> None:
        self._stop.set()
        with self._lock:
            bridges, self._bridges = list(self._bridges.values()), {}
        for b in bridges:
            b.stop()

    # ------------------------------------------------------------------ #
    # access
    # ------------------------------------------------------------------ #

    def _spawn(self, arxiv_id: str, session_path: str | None) -> PiBridge:
        ws = workspace_dir(arxiv_id)
        if not ws.exists():
            raise PiBridgeError(
                f"No workspace for {arxiv_id}. Run /api/chat/prepare first."
            )
        outline = ws / "OUTLINE.md"
        b = PiBridge(
            arxiv_id,
            workspace=ws,
            session_dir=sessions_dir(arxiv_id),
            session_path=session_path,
            outline_path=outline if outline.exists() else None,
            tools=config.CHAT_TOOLS,
            pi_bin=config.PI_BIN,
            model=config.CHAT_MODEL,
            thinking=config.CHAT_THINKING,
            extensions=config.PI_EXTENSIONS,
        )
        b.start()
        return b

    def acquire(self, arxiv_id: str) -> PiBridge:
        """Get the live pi process for this paper, spawning one if needed.

        A respawn resumes the paper's **most recent** conversation, so eviction
        and server restarts never silently fork the history into a new session.
        """
        with self._lock:
            b = self._bridges.get(arxiv_id)
            if b is not None and b.alive:
                return b
            if b is not None:                     # died; replace it
                b.stop()
                del self._bridges[arxiv_id]
            b = self._spawn(arxiv_id, session_path=latest_session(arxiv_id))
            self._bridges[arxiv_id] = b
            return b

    def respawn(self, arxiv_id: str, session_path: str | None = None,
                fresh: bool = False) -> PiBridge:
        """Replace the process, bound to a specific (or fresh) conversation.

        Existing SSE subscribers are migrated to the new process so an open
        panel keeps receiving events — and the outgoing process is marked
        ``_replaced`` first, so it does not announce a bogus ``exited`` that
        would leave the UI showing a connection error after every switch.
        """
        if fresh:
            session_path = None
        elif session_path is None:
            session_path = latest_session(arxiv_id)

        with self._lock:
            old = self._bridges.pop(arxiv_id, None)
            carried = list(old._subscribers) if old is not None else []
            if old is not None:
                old._replaced = True          # silence its exit events
            new = self._spawn(arxiv_id, session_path=session_path)
            self._bridges[arxiv_id] = new
            # Re-attach existing subscribers before stopping the old process, so
            # there is no window where events have nowhere to go.
            for q in carried:
                new._subscribers.add(q)

        if old is not None:
            old.stop()
        new._broadcast({"type": "reaper_bridge", "state": "session_switched",
                        "session": session_path})
        return new

    def subscribe(self, arxiv_id: str):
        """Return ``(bridge, queue)``; caller must call ``release`` when done."""
        b = self.acquire(arxiv_id)
        return b, b.subscribe()

    def release(self, arxiv_id: str, q) -> None:
        with self._lock:
            b = self._bridges.get(arxiv_id)
        if b is not None:
            b.unsubscribe(q)

    def shutdown(self, arxiv_id: str) -> bool:
        """Stop the process for one paper (the on-disk session survives)."""
        with self._lock:
            b = self._bridges.pop(arxiv_id, None)
        if b is None:
            return False
        b.stop()
        return True

    def is_running(self, arxiv_id: str) -> bool:
        with self._lock:
            b = self._bridges.get(arxiv_id)
        return b is not None and b.alive

    def current(self, arxiv_id: str) -> PiBridge | None:
        """The live bridge for this paper, if any (no spawning)."""
        with self._lock:
            b = self._bridges.get(arxiv_id)
        return b if (b is not None and b.alive) else None

    def status(self) -> list[dict]:
        with self._lock:
            bridges = list(self._bridges.values())
        return [{
            "arxiv_id": b.arxiv_id,
            "alive": b.alive,
            "pid": b.pid,
            "session": b.session_path,
            "idle": round(time.monotonic() - b.last_active, 1),
            "subscribers": len(b._subscribers),
        } for b in bridges]


# One registry per server process.
registry = PiSessionRegistry()
