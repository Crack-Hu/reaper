"""HTTP surface for the chat feature.

Mounted by `src/server.py`; kept separate so the SSE plumbing does not bloat the
main request handler.

Transport shape (mirrors pi's own command semantics):

    POST /api/chat          send a message — returns *immediately* with
                            {"accepted": bool, "error": str|null}
    GET  /api/chat/stream   SSE; streams pi's events until the run settles
    POST /api/chat/abort    cancel the current run
    POST /api/chat/prepare  build the agent workspace for a paper
    POST /api/chat/reset    start a fresh conversation
    GET  /api/chat/health   process + connection status

Splitting "send" from "stream" means a dropped connection never loses the
message, and no single request has to stay open for the whole answer.

Security
--------
The server binds 0.0.0.0 by default, but the agent can read files, so these
endpoints are **loopback-only** unless `chat.allow_remote` is explicitly set in
config.json.
"""

from __future__ import annotations

import json
import queue
import time
from pathlib import Path

from .. import config
from .bridge import PiBridgeError
from .context import prepare_paper_context, workspace_dir
from .session import (delete_session, latest_session, list_sessions,
                      registry, resolve_session)

# Phase 0 spike page. Served from the same origin as the API so the browser
# does not need CORS, and so it mirrors how the Zotero panel will fetch.
PROTOTYPE_PAGE = Path(config.ROOT) / "prototype" / "chat.html"

# SSE tuning. The stream is a *persistent subscription* to the paper's event
# bus, not a per-message request: it stays open across turns so that every open
# panel sees every turn, no matter which one asked. Dead clients are detected by
# the heartbeat write failing, so there is no idle timeout.
HEARTBEAT_SECONDS = 15.0

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def _allow_remote() -> bool:
    return bool(config.CHAT_ALLOW_REMOTE)


def _is_loopback(handler) -> bool:
    try:
        return handler.client_address[0] in _LOOPBACK
    except Exception:
        return False


def _guard(handler) -> bool:
    """Reject non-loopback callers unless explicitly allowed."""
    if _allow_remote() or _is_loopback(handler):
        return True
    handler._respond_json(
        {"error": "chat endpoints are loopback-only; set chat.allow_remote to override"},
        status=403,
    )
    return False


def _require_id(handler, arxiv_id) -> bool:
    if arxiv_id:
        return True
    handler._respond_json({"error": "missing arxiv_id"}, status=400)
    return False


def _busy(bridge) -> bool:
    """True while pi is mid-run (or retrying / compacting).

    Tree-mutating operations must not run then: pi issue #5096 documents that
    navigating during tool execution appends tool results with the wrong
    `parentId`, which corrupts the session. The maintainer's guidance was to
    disallow structural operations during streaming, so we refuse rather than
    risk the tree. The pi extension enforces the same rule independently.
    """
    try:
        return bool(bridge.get_state().get("isStreaming"))
    except PiBridgeError:
        return False


# --------------------------------------------------------------------------- #
# GET
# --------------------------------------------------------------------------- #

def handle_get(handler, parsed, qs: dict) -> bool:
    """Handle a chat GET. Returns True if the path was ours."""
    path = parsed.path

    if path == "/api/chat/stream":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            if _require_id(handler, arxiv_id):
                _stream(handler, arxiv_id)
        return True

    if path == "/api/chat/health":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            _health(handler, arxiv_id)
        return True

    if path == "/api/chat/sessions":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            if _require_id(handler, arxiv_id):
                _sessions(handler, arxiv_id)
        return True

    if path == "/api/chat/messages":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            if _require_id(handler, arxiv_id):
                _messages(handler, arxiv_id)
        return True

    if path == "/api/chat/tree":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            if _require_id(handler, arxiv_id):
                _tree(handler, arxiv_id)
        return True

    if path == "/api/chat/commands":
        if _guard(handler):
            arxiv_id = (qs.get("arxiv_id") or [None])[0]
            if _require_id(handler, arxiv_id):
                _commands(handler, arxiv_id)
        return True

    if path == "/api/chat/prototype":
        if _guard(handler):
            _prototype(handler)
        return True

    return False


def _sessions(handler, arxiv_id: str) -> None:
    """The conversation list for this paper (newest first).

    ``current`` is the conversation the UI should present as active. Two cases:

    * A process is running: use ``get_state().sessionFile`` — pi is
      authoritative, and ``/api/chat/reset`` can swap the session inside a
      running process, leaving our spawn-time path stale.
    * No process yet: the next ``registry.acquire()`` resumes the **newest**
      conversation, so that is what is current. Reporting ``null`` here made the
      picker fall back to a bare "会话" even though sessions existed.

    ``fresh`` means a genuinely new conversation that pi has not written to disk
    yet (pi allocates a path immediately but only creates the file once the first
    assistant message lands).
    """
    sessions = list_sessions(arxiv_id)
    latest = latest_session(arxiv_id)
    current = None
    fresh = False
    running = False

    cur = registry.current(arxiv_id)
    if cur is not None:
        running = True
        current = cur.session_path
        try:
            current = cur.get_state().get("sessionFile") or current
        except PiBridgeError:
            pass
        if not current or not Path(current).exists():
            fresh = True
    else:
        current = latest

    handler._respond_json({
        "ok": True,
        "arxiv_id": arxiv_id,
        "sessions": sessions,
        "latest": latest,
        "current": current,
        "fresh": fresh,
        "running": running,
    })


def _messages(handler, arxiv_id: str) -> None:
    """The live conversation, straight from pi (so it is authoritative)."""
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": True, "messages": [], "running": False})
        return
    try:
        bridge = registry.acquire(arxiv_id)
        # `sessionFile` from pi is authoritative: `/api/chat/reset` swaps the
        # session inside the running process, so the path we spawned with can be
        # stale.
        current = bridge.session_path
        try:
            current = bridge.get_state().get("sessionFile") or current
        except PiBridgeError:
            pass
        handler._respond_json({"ok": True, "running": True,
                               "session": current,
                               "messages": bridge.get_messages()})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _tree(handler, arxiv_id: str) -> None:
    """Everything the TUI's `/session` and `/tree` would show, in one call."""
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": True, "running": False,
                               "tree": [], "stats": {}, "forkable": []})
        return
    try:
        bridge = registry.acquire(arxiv_id)
        tree = bridge.get_tree()          # one round trip, not two
        handler._respond_json({
            "ok": True,
            "running": True,
            "session": bridge.session_path,
            "tree": tree.get("tree", []),
            "leafId": tree.get("leafId"),
            "stats": bridge.get_stats(),
            "forkable": bridge.get_fork_messages(),
        })
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _commands(handler, arxiv_id: str) -> None:
    """Extension / prompt-template / skill commands.

    Built-in TUI commands are not listed by pi; their behaviour is exposed
    through the dedicated endpoints instead.
    """
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": True, "running": False, "commands": []})
        return
    try:
        handler._respond_json({"ok": True, "running": True,
                               "commands": registry.acquire(arxiv_id).get_commands()})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _prototype(handler) -> None:
    """Serve the Phase 0 spike page (same-origin, so no CORS)."""
    if not PROTOTYPE_PAGE.exists():
        handler._respond_json({"error": "prototype/chat.html not found"}, status=404)
        return
    handler._respond_html(PROTOTYPE_PAGE.read_text(encoding="utf-8"))


def _health(handler, arxiv_id: str | None) -> None:
    payload = {"ok": True, "processes": registry.status()}
    if arxiv_id:
        ws = workspace_dir(arxiv_id)
        payload["workspace"] = {"path": str(ws), "ready": ws.exists()}
        if registry.is_running(arxiv_id):
            try:
                payload["bridge"] = registry.acquire(arxiv_id).health()
            except PiBridgeError as e:
                payload["bridge"] = {"error": str(e)}
    handler._respond_json(payload)


def _stream(handler, arxiv_id: str) -> None:
    """Persistent SSE subscription to this paper's event bus.

    Deliberately **not** closed when a turn settles: several panels can be open
    on the same paper, and every one of them must see every turn regardless of
    which panel asked. The connection ends only when the client goes away or the
    pi process dies.
    """
    try:
        bridge, q = registry.subscribe(arxiv_id)
    except PiBridgeError as e:
        handler._respond_json({"error": str(e)}, status=503)
        return

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")     # disable proxy buffering
    handler.end_headers()

    last_write = time.monotonic()
    try:
        _sse(handler, {"type": "reaper_bridge", "state": "connected",
                       "arxiv_id": arxiv_id,
                       "session": bridge.session_path})
        while True:
            # Look the bridge up each pass: a conversation switch replaces the
            # process, and the registry carries our subscription across.
            cur = registry.current(arxiv_id)
            if cur is None:
                _sse(handler, {"type": "reaper_bridge", "state": "exited"})
                break
            try:
                event = q.get(timeout=1.0)
            except queue.Empty:
                now = time.monotonic()
                if now - last_write >= HEARTBEAT_SECONDS:
                    # Also our only reliable way to notice a dead client.
                    handler.wfile.write(b": ping\n\n")
                    handler.wfile.flush()
                    last_write = now
                continue

            _sse(handler, event)
            last_write = time.monotonic()
    except (BrokenPipeError, ConnectionResetError):
        pass                                            # client went away
    except Exception as e:                              # pragma: no cover
        try:
            _sse(handler, {"type": "reaper_bridge", "state": "stream_error",
                           "error": str(e)})
        except Exception:
            pass
    finally:
        registry.release(arxiv_id, q)


def _sse(handler, event: dict) -> None:
    payload = json.dumps(event, ensure_ascii=False)
    handler.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
    handler.wfile.flush()


# --------------------------------------------------------------------------- #
# POST
# --------------------------------------------------------------------------- #

def handle_post(handler, parsed, data: dict) -> bool:
    """Handle a chat POST. Returns True if the path was ours."""
    path = parsed.path

    if path == "/api/chat":
        if _guard(handler):
            _prompt(handler, data)
        return True

    if path == "/api/chat/abort":
        if _guard(handler):
            _abort(handler, data)
        return True

    if path == "/api/chat/prepare":
        if _guard(handler):
            _prepare(handler, data)
        return True

    if path == "/api/chat/reset":
        if _guard(handler):
            _reset(handler, data)
        return True

    if path == "/api/chat/open":
        if _guard(handler):
            _open(handler, data)
        return True

    if path == "/api/chat/new":
        if _guard(handler):
            _new(handler, data)
        return True

    if path == "/api/chat/rename":
        if _guard(handler):
            _rename(handler, data)
        return True

    if path == "/api/chat/fork":
        if _guard(handler):
            _fork(handler, data)
        return True

    if path == "/api/chat/clone":
        if _guard(handler):
            _clone(handler, data)
        return True

    if path == "/api/chat/delete":
        if _guard(handler):
            _delete(handler, data)
        return True

    if path == "/api/chat/export":
        if _guard(handler):
            _export(handler, data)
        return True

    if path == "/api/chat/navigate":
        if _guard(handler):
            _navigate(handler, data)
        return True

    if path == "/api/chat/label":
        if _guard(handler):
            _label(handler, data)
        return True

    return False


# pi's RPC surface has no `navigate_tree`, so these two go through our own pi
# extension (pi-extensions/reaper-tree.ts) by invoking its commands as prompts.
# Extension commands execute immediately, even mid-stream.

def _navigate(handler, data: dict) -> None:
    """Move the active branch to an entry — the TUI's `/tree` navigation."""
    arxiv_id = data.get("arxiv_id")
    entry_id = (data.get("entryId") or "").strip()
    if not _require_id(handler, arxiv_id):
        return
    if not entry_id:
        handler._respond_json({"error": "missing entryId"}, status=400)
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    cmd = f"/goto {entry_id}" + (" summary" if data.get("summarize") else "")
    try:
        bridge = registry.acquire(arxiv_id)
        if _busy(bridge):
            handler._respond_json({
                "ok": False,
                "error": "agent 正在运行中，请先等它结束或中断——运行中移动分支会破坏会话树",
                "busy": True,
            }, status=409)
            return
        res = bridge.prompt(cmd)
        handler._respond_json({"ok": res["accepted"], "error": res.get("error")})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _label(handler, data: dict) -> None:
    """Set or clear an entry label (bookmarks the tree view shows)."""
    arxiv_id = data.get("arxiv_id")
    entry_id = (data.get("entryId") or "").strip()
    text = (data.get("label") or "").strip()
    if not _require_id(handler, arxiv_id):
        return
    if not entry_id:
        handler._respond_json({"error": "missing entryId"}, status=400)
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    cmd = f"/unlabel {entry_id}" if not text else f"/label {entry_id} {text}"
    try:
        bridge = registry.acquire(arxiv_id)
        if _busy(bridge):
            handler._respond_json({
                "ok": False,
                "error": "agent 正在运行中，请先等它结束或中断",
                "busy": True,
            }, status=409)
            return
        res = bridge.prompt(cmd)
        handler._respond_json({"ok": res["accepted"], "error": res.get("error")})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _rename(handler, data: dict) -> None:
    """Name the current conversation (or a saved one) so the list is readable."""
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    name = (data.get("name") or "").strip()
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    try:
        handler._respond_json({"ok": registry.acquire(arxiv_id).set_session_name(name)})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _fork(handler, data: dict) -> None:
    """Branch off from an earlier user message into a new conversation."""
    arxiv_id = data.get("arxiv_id")
    entry_id = (data.get("entryId") or "").strip()
    if not _require_id(handler, arxiv_id):
        return
    if not entry_id:
        handler._respond_json({"error": "missing entryId"}, status=400)
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    try:
        res = registry.acquire(arxiv_id).fork(entry_id)
        handler._respond_json({"ok": not res.get("cancelled"), **res})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _clone(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    try:
        res = registry.acquire(arxiv_id).clone()
        handler._respond_json({"ok": not res.get("cancelled"), **res})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _delete(handler, data: dict) -> None:
    """Delete a saved conversation, including the one currently open.

    A conversation pi currently has open cannot be unlinked underneath it, so
    when the target is active we first move the process onto the next most
    recent conversation (or a fresh one when this was the last), then delete.
    That is what \"delete this conversation\" has to mean if it is to be
    reachable at all — otherwise the button can never do anything.
    """
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    target = data.get("session") or ""
    allow_permanent = bool(data.get("permanent"))

    result = delete_session(arxiv_id, target, allow_permanent=allow_permanent)
    switched_to = None
    if not result.get("ok") and result.get("active"):
        path = result.get("path")
        try:
            nxt = next((s for s in list_sessions(arxiv_id) if s["path"] != path), None)
            if nxt:
                registry.respawn(arxiv_id, session_path=nxt["path"])
                switched_to = nxt["path"]
            else:
                registry.respawn(arxiv_id, fresh=True)
            result = delete_session(arxiv_id, target,
                                    allow_permanent=allow_permanent)
            result["switched"] = True
            result["switched_to"] = switched_to
        except PiBridgeError as e:
            result = {"ok": False, "error": f"无法切走以删除：{e}"}

    handler._respond_json(result, status=200 if result.get("ok") else 409)


def _export(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": False, "error": "没有运行中的会话"}, status=409)
        return
    out = data.get("path")
    if not out:
        out = str(Path(config.chat_dir(arxiv_id)) / "export.html")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
    try:
        p = registry.acquire(arxiv_id).export_html(out)
        handler._respond_json({"ok": bool(p), "path": p})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _open(handler, data: dict) -> None:
    """Switch this paper to a saved conversation and rebind the pi process."""
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    target = (data.get("session") or "").strip()
    if not target:
        handler._respond_json({"error": "missing session"}, status=400)
        return
    path = resolve_session(arxiv_id, target)
    if not path:
        handler._respond_json({"error": f"unknown session: {target}"}, status=404)
        return
    try:
        registry.respawn(arxiv_id, session_path=path)
        handler._respond_json({"ok": True, "session": path})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _new(handler, data: dict) -> None:
    """Start a brand-new conversation for this paper."""
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    try:
        registry.respawn(arxiv_id, fresh=True)
        handler._respond_json({"ok": True, "fresh": True})
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=503)


def _prompt(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    message = (data.get("message") or "").strip()
    if not _require_id(handler, arxiv_id):
        return
    if not message:
        handler._respond_json({"error": "empty message"}, status=400)
        return

    try:
        bridge = registry.acquire(arxiv_id)
    except PiBridgeError as e:
        handler._respond_json({"ok": False, "accepted": False, "error": str(e)},
                              status=503)
        return

    try:
        result = bridge.prompt(message)
    except PiBridgeError as e:
        result = {"accepted": False, "error": str(e)}

    # `accepted` only means pi took the message; the answer arrives on
    # /api/chat/stream. A rejection carries pi's own explanation, which is
    # usually actionable ("No API key found for the selected model").
    handler._respond_json({"ok": result["accepted"], **result})


def _abort(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": True, "aborted": False, "reason": "not running"})
        return
    handler._respond_json({"ok": True,
                           "aborted": registry.acquire(arxiv_id).abort()})


def _prepare(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    try:
        info = prepare_paper_context(arxiv_id, force=bool(data.get("force")))
        handler._respond_json({"ok": True, **info})
    except FileNotFoundError as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=404)
    except Exception as e:
        handler._respond_json({"ok": False, "error": str(e)}, status=500)


def _reset(handler, data: dict) -> None:
    arxiv_id = data.get("arxiv_id")
    if not _require_id(handler, arxiv_id):
        return
    if not registry.is_running(arxiv_id):
        handler._respond_json({"ok": True, "reset": True, "reason": "no live process"})
        return
    handler._respond_json({"ok": True,
                           "reset": registry.acquire(arxiv_id).new_session()})
