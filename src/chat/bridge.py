"""Drive a `pi --mode rpc` subprocess over stdio (JSONL) and fan out its events.

Why a subprocess and not an HTTP client: pi only speaks JSONL over stdin/stdout.
Our Python server *is* the bridge between the Zotero plugin (HTTP/SSE) and pi
(stdio/JSONL), which keeps the plugin a pure UI layer and leaves session
management, the tool loop, retries and compaction entirely to pi.

Protocol notes (from pi's docs/rpc.md):
* Records are separated by a single ``\\n``. **Split on ``\\n`` only** — a
  generic line reader that also splits on U+2028/U+2029 (both legal inside JSON
  strings) would corrupt messages. Hence we read in binary and split the buffer
  ourselves.
* Commands are JSON objects written to stdin: ``{"type": "prompt", ...}``.
* Events are JSON objects on stdout. Events are *not* replies: pi pushes them
  whenever it wants, so one dedicated reader thread owns stdout for the whole
  lifetime of the process and broadcasts to subscribers.
* A command may carry an ``id``; the matching reply is
  ``{"type": "response", "id": <same>, "command": ..., "success": bool}``.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

# How long a `prompt` command may take to be *accepted* (not to finish).
ACCEPT_TIMEOUT = 60.0

# How long a blocking request/response command may take.
REQUEST_TIMEOUT = 30.0


class PiBridgeError(RuntimeError):
    """pi could not be started, or died while we were talking to it."""


class PiBridge:
    """One `pi --mode rpc` process, plus event fan-out.

    Lifecycle: ``start()`` → ``prompt()``/``abort()`` → ``stop()``.
    Instances are not reusable after ``stop()``.
    """

    def __init__(
        self,
        arxiv_id: str,
        workspace: Path,
        session_dir: Path,
        *,
        outline_path: Path | None = None,
        session_path: str | None = None,
        tools: str = "read,grep,find,ls",
        pi_bin: str = "pi",
        model: str | None = None,
        thinking: str | None = None,
        extensions: list[str] | None = None,
    ) -> None:
        self.arxiv_id = arxiv_id
        self.workspace = Path(workspace)
        self.session_dir = Path(session_dir)
        # Resolve to an absolute path up front. pi resolves `--session` relative
        # to its cwd (the workspace), and — worse — silently starts a *fresh*
        # session when the path does not exist. That failure mode looks exactly
        # like "my history vanished", so we refuse to start instead.
        if session_path:
            resolved = Path(session_path)
            if not resolved.is_absolute():
                resolved = (Path.cwd() / resolved).resolve()
            if not resolved.exists():
                raise PiBridgeError(
                    f"session file not found: {resolved} (refusing to start a new "
                    f"session, which would silently fork the conversation)"
                )
            session_path = str(resolved)
        self.session_path = session_path
        self.outline_path = Path(outline_path) if outline_path else None
        self.tools = tools
        self.pi_bin = pi_bin
        self.model = model
        self.thinking = thinking
        self.extensions = extensions or []

        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._subscribers: set[queue.Queue] = set()
        self._sub_lock = threading.Lock()
        # Events of the *currently running* turn, replayed to clients that
        # subscribe mid-run. Cleared when a new run starts so a client can never
        # receive a previous turn's output.
        self._history: list[dict] = []
        self._run_active = False

        self._pending: dict[str, threading.Event] = {}
        self._responses: dict[str, dict] = {}
        self._req_lock = threading.Lock()
        self._req_seq = 0
        # 串行化 stdin 写入。pi 的协议是「一行一个 JSON」，而管道的写入只保证
        # 小于 PIPE_BUF 的原子性 —— 并发的长 prompt 会交错并损坏协议。
        self._write_lock = threading.Lock()

        self._stderr: list[str] = []
        self.last_active = time.monotonic()
        self.started_at = 0.0
        # Set when this process is deliberately replaced (conversation switch).
        # Its dying reader thread must then stay quiet: an `exited` event means
        # "the connection is gone", and a swap is not that — clients would latch
        # onto the error state and never recover.
        self._replaced = False

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Spawn pi and begin reading its event stream."""
        if self._proc is not None:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.pi_bin, "--mode", "rpc",
            "--session-dir", str(self.session_dir),
            "--tools", self.tools,
        ]
        # Resume a specific conversation. We pass the path explicitly instead of
        # using `--continue`: it is predictable, and it lets the UI open any past
        # conversation rather than only the newest one. Without it, pi starts a
        # brand-new session on every spawn.
        if self.session_path:
            cmd += ["--session", str(self.session_path)]
        # Extensions that add the commands pi's own RPC surface lacks.
        for ext in self.extensions:
            cmd += ["--extension", str(ext)]
        if self.outline_path and self.outline_path.exists():
            # pi accepts a path here and injects the file's contents into the
            # system prompt, which is how the paper outline reaches the model.
            cmd += ["--append-system-prompt", str(self.outline_path)]
        if self.model:
            cmd += ["--model", self.model]
        if self.thinking:
            cmd += ["--thinking", self.thinking]

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,           # binary, unbuffered — we do our own framing
            )
        except FileNotFoundError as e:
            raise PiBridgeError(
                f"`{self.pi_bin}` not found. Install pi or set chat.pi_bin in config.json."
            ) from e

        self.started_at = time.monotonic()
        self._reader = threading.Thread(
            target=self._reader_loop, name=f"pi-reader-{self.arxiv_id}", daemon=True
        )
        self._reader.start()
        threading.Thread(
            target=self._stderr_loop, name=f"pi-stderr-{self.arxiv_id}", daemon=True
        ).start()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def stop(self, timeout: float = 5.0) -> None:
        """Terminate pi, escalating to SIGKILL if it does not exit."""
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.close()          # EOF is the polite shutdown
                except Exception:
                    pass
                try:
                    proc.terminate()
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=timeout)
        finally:
            self._broadcast({"type": "reaper_bridge", "state": "stopped"})

    # ------------------------------------------------------------------ #
    # reading
    # ------------------------------------------------------------------ #

    def _reader_loop(self) -> None:
        """Own pi's stdout for the life of the process; broadcast every event."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        buf = b""
        try:
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") \
                    else proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                # Strict JSONL: LF is the only record delimiter.
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line, buf = buf[:nl], buf[nl + 1:]
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    if line:
                        self._handle_line(line)
        except Exception as e:                     # pragma: no cover - defensive
            self._broadcast({"type": "reaper_bridge", "state": "reader_error",
                             "error": str(e)})
        finally:
            if buf.strip():                        # unterminated tail
                self._handle_line(buf)
            rc = proc.poll()
            if not self._replaced:
                self._broadcast({"type": "reaper_bridge", "state": "exited",
                                 "exit_code": rc})
            self._wake_pending()

    def _handle_line(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return                                  # torn/partial line: skip
        if not isinstance(msg, dict):
            return

        if msg.get("type") == "response" and msg.get("id"):
            rid = str(msg["id"])
            with self._req_lock:
                ev = self._pending.pop(rid, None)
                if ev is not None:
                    self._responses[rid] = msg
                # A reply nobody is waiting for must not accumulate forever.
                while len(self._responses) > 32:
                    self._responses.pop(next(iter(self._responses)))
            if ev:
                ev.set()

        self._broadcast(msg)

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._stderr.append(text)
                    del self._stderr[:-50]          # keep the last 50 lines
                    self._broadcast({"type": "reaper_bridge", "state": "stderr",
                                     "text": text})
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # fan-out
    # ------------------------------------------------------------------ #

    def subscribe(self) -> queue.Queue:
        """Register a subscriber. Caller must call ``unsubscribe``.

        If a turn is currently running, its events so far are replayed into the
        queue first, so a client that subscribes *after* the prompt was accepted
        does not miss the beginning of the answer.
        """
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._sub_lock:
            self._subscribers.add(q)
            if self._run_active:
                for ev in self._history:
                    try:
                        q.put_nowait(ev)
                    except queue.Full:
                        break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            self._subscribers.discard(q)

    def _broadcast(self, event: dict) -> None:
        kind = event.get("type")
        with self._sub_lock:
            # A fresh run starts a fresh replay buffer; a settled run stops
            # accumulating but keeps what it produced for late subscribers.
            if kind == "agent_start":
                self._history = []
                self._run_active = True
            if self._run_active:
                self._history.append(event)
            if kind == "agent_settled":
                self._run_active = False
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                # A stalled client must not block pi's reader thread. Drop the
                # oldest event and keep going.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #

    def _send(self, cmd: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise PiBridgeError("pi is not running")
        line = (json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8")
        # 整个「写入 + flush」必须是一段临界区，否则两个线程的字节会交错，
        # pi 会读到半条 JSON。
        with self._write_lock:
            proc.stdin.write(line)
            proc.stdin.flush()
        self.last_active = time.monotonic()

    def _request(self, cmd: dict, timeout: float = REQUEST_TIMEOUT) -> dict:
        """Send a command and wait for its matching `response`."""
        with self._req_lock:
            self._req_seq += 1
            rid = f"reaper-{self._req_seq}"
        cmd = {**cmd, "id": rid}
        ev = threading.Event()
        with self._req_lock:
            self._pending[rid] = ev
        try:
            self._send(cmd)
            if not ev.wait(timeout):
                raise PiBridgeError(f"timeout waiting for `{cmd.get('type')}` reply")
            with self._req_lock:
                return self._responses.pop(rid, {})
        finally:
            with self._req_lock:
                self._pending.pop(rid, None)

    def _wake_pending(self) -> None:
        with self._req_lock:
            events = list(self._pending.values())
            self._pending.clear()
        for ev in events:
            ev.set()

    # -- public commands --

    def prompt(self, message: str, streaming_behavior: str | None = None) -> dict:
        """Send a user message.

        Returns ``{"accepted": bool, "error": str | None}``.

        ``accepted`` means pi took the message — **not** that the answer is
        finished. Follow the event stream until ``agent_settled``. When pi
        rejects before acceptance it explains why (e.g. "No API key found for
        the selected model"), and callers should surface that verbatim rather
        than leaving the user waiting for a reply that will never come.
        """
        cmd: dict = {"type": "prompt", "message": message}
        if streaming_behavior:
            cmd["streamingBehavior"] = streaming_behavior
        resp = self._request(cmd, timeout=ACCEPT_TIMEOUT)
        ok = bool(resp.get("success"))
        return {"accepted": ok, "error": None if ok else (resp.get("error") or "prompt rejected")}

    def abort(self) -> bool:
        try:
            resp = self._request({"type": "abort"}, timeout=10)
            return bool(resp.get("success"))
        except PiBridgeError:
            return False

    def get_state(self) -> dict:
        resp = self._request({"type": "get_state"})
        return resp.get("data", {}) if resp.get("success") else {}

    def new_session(self) -> bool:
        resp = self._request({"type": "new_session"})
        data = resp.get("data") or {}
        return bool(resp.get("success")) and not data.get("cancelled")

    # -- session introspection (the RPC equivalents of the TUI's /session,
    #    /tree, /fork, /clone and /name) --

    def get_stats(self) -> dict:
        """Tokens, cost and current context-window usage (TUI `/session`)."""
        resp = self._request({"type": "get_session_stats"})
        return resp.get("data", {}) if resp.get("success") else {}

    def get_tree(self) -> dict:
        """The session as a tree of entries (TUI `/tree`).

        Each node is ``{entry, children, label?, labelTimestamp?}``; ``leafId``
        says which branch is currently active.
        """
        resp = self._request({"type": "get_tree"}, timeout=60)
        return resp.get("data", {}) if resp.get("success") else {}

    def get_fork_messages(self) -> list:
        """User messages that can be forked from, as {entryId, text}."""
        resp = self._request({"type": "get_fork_messages"})
        return (resp.get("data") or {}).get("messages", []) if resp.get("success") else []

    def set_session_name(self, name: str) -> bool:
        resp = self._request({"type": "set_session_name", "name": name})
        return bool(resp.get("success"))

    def fork(self, entry_id: str) -> dict:
        """Branch off from a previous user message into a new session."""
        resp = self._request({"type": "fork", "entryId": entry_id}, timeout=120)
        return resp.get("data", {}) if resp.get("success") else {}

    def clone(self) -> dict:
        """Duplicate the current branch into a new session."""
        resp = self._request({"type": "clone"}, timeout=120)
        return resp.get("data", {}) if resp.get("success") else {}

    def export_html(self, output_path: str | None = None) -> str | None:
        cmd: dict = {"type": "export_html"}
        if output_path:
            cmd["outputPath"] = output_path
        resp = self._request(cmd, timeout=120)
        return (resp.get("data") or {}).get("path") if resp.get("success") else None

    def get_commands(self) -> list:
        """Extension / prompt-template / skill commands usable via `prompt`.

        Built-in TUI commands (`/tree`, `/session`, …) are deliberately NOT in
        here — pi only handles those in interactive mode. Their behaviour is
        reached through the RPC commands above instead.
        """
        resp = self._request({"type": "get_commands"})
        return (resp.get("data") or {}).get("commands", []) if resp.get("success") else []

    def get_messages(self) -> list:
        resp = self._request({"type": "get_messages"})
        return (resp.get("data") or {}).get("messages", []) if resp.get("success") else []

    def health(self) -> dict:
        """Cheap status probe for the UI's connection indicator."""
        out = {
            "arxiv_id": self.arxiv_id,
            "alive": self.alive,
            "pid": self.pid,
            "uptime": round(time.monotonic() - self.started_at, 1) if self.started_at else 0,
            "idle": round(time.monotonic() - self.last_active, 1),
            "subscribers": len(self._subscribers),
            "stderr_tail": self._stderr[-3:],
        }
        if self.alive:
            try:
                st = self.get_state()
                out["streaming"] = st.get("isStreaming")
                out["model"] = (st.get("model") or {}).get("id")
                out["session_id"] = st.get("sessionId")
            except PiBridgeError as e:
                out["error"] = str(e)
        return out
