"""日志：并发任务的可读输出。

问题
----
多个任务并行时（不同论文的生成/对话），所有输出混在同一个追加流里交错，
无法跟读任何单个任务。而且进度条每刷一次就多几行噪音。

三层方案
--------
1. **终端状态面板**（仅 TTY）—— 底部固定一块，每个活跃任务一行，就地刷新：
   阶段、百分比、耗时。日志行在它上面滚动。这是真正解决「并行时看不过
   来」的部分：不用滚动、不用 grep，一眼看到所有任务现在在做什么。

2. **每个任务一份日志**（``logs/papers/{arxiv_id}.log``）—— 完整历史，
   ``tail -f`` 即可干净跟读单篇论文，永不交错。状态面板给「现在」，
   这个文件给「历史」。

3. **进度不再刷屏** —— 进度条改成就地更新状态面板，不再每次输出一行。
   重定向到文件时（非 TTY）面板自动关闭，日志保持纯文本。

行格式：``HH:MM:SS  2210.00921 ▸ 消息``；完整日期只在任务开始/结束的
横幅上出现一次。
"""

from __future__ import annotations

import builtins
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# ── 状态 ──

_ctx = threading.local()
_lock = threading.Lock()
_merged_file = None
_papers_dir: Path | None = None
_task_files: dict[str, object] = {}
_original_print = builtins.print
_installed = False

# 活跃任务：arxiv_id → {started, phase, pct, note}
_tasks: dict[str, dict] = {}
_block_lines = 0          # 当前在屏幕上画了几行
_tty: bool | None = None


def configure(log_dir: str, papers_subdir: str = "papers") -> None:
    """安装 print 钩子并打开合并日志。可重复调用（幂等）。"""
    global _merged_file, _papers_dir, _installed, _tty
    if _installed:
        return
    log_path = Path(log_dir) / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _merged_file = open(str(log_path), "a", encoding="utf-8")
    _papers_dir = Path(log_dir) / papers_subdir
    _tty = sys.stdout.isatty() if os.environ.get("REAPER_NO_STATUS_BLOCK") != "1" else False
    builtins.print = _hooked_print
    _installed = True


def merged_log_path() -> str | None:
    return getattr(_merged_file, "name", None)


def task_log_path(arxiv_id: str) -> str | None:
    return str(_papers_dir / f"{arxiv_id}.log") if _papers_dir else None


def status_block_enabled() -> bool:
    return bool(_tty)


# --------------------------------------------------------------------------- #
# task context
# --------------------------------------------------------------------------- #

def current_task() -> str | None:
    return getattr(_ctx, "arxiv_id", None)


@contextmanager
def task(arxiv_id: str):
    """把当前线程标记为在处理 ``arxiv_id``，并给它开一份独立日志。"""
    previous = getattr(_ctx, "arxiv_id", None)
    _ctx.arxiv_id = arxiv_id

    with _lock:
        _tasks[arxiv_id] = {"started": time.monotonic(), "phase": "启动",
                            "pct": None, "note": ""}
    _banner(arxiv_id, "开始")
    if _tty:
        print(f"  完整日志: tail -f {task_log_path(arxiv_id)}")

    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        with _lock:
            _tasks.pop(arxiv_id, None)
        _banner(arxiv_id, f"结束（{elapsed:.1f}s）")
        _ctx.arxiv_id = previous
        _close_task_file(arxiv_id)
        _redraw()


def set_progress(phase: str | None = None, pct: float | None = None,
                 note: str | None = None) -> None:
    """更新当前任务在状态面板上的进度。不产生日志行。

    这是替代「每次进度都 print 一行」的接口：调它只刷新面板，所以并行时
    不会刷屏，日志文件也不会被进度条灌满。
    """
    aid = current_task()
    if not aid:
        return
    with _lock:
        st = _tasks.get(aid)
        if st is None:
            return
        if phase is not None:
            st["phase"] = phase
        if pct is not None:
            st["pct"] = max(0.0, min(100.0, float(pct)))
        if note is not None:
            st["note"] = note
    _redraw()


# --------------------------------------------------------------------------- #
# status block (TTY only)
# --------------------------------------------------------------------------- #

def _block_render() -> list[str]:
    with _lock:
        items = sorted(_tasks.items())
    if not items:
        return []
    width = max(len(a) for a, _ in items)
    now = time.monotonic()
    out = []
    for aid, st in items:
        phase = (st.get("phase") or "…")[:26]
        note = (st.get("note") or "")[:14]
        pct = st.get("pct")
        # 列是条件性的：用不到的列不占位（面板每次都会先擦再画，
        # 所以宽度变化不会留下残影）。
        parts = [f"  {aid:<{width}}", f"{phase:<26}"]
        if note:
            parts.append(f"{note:<14}")
        if pct is not None:
            filled = int(pct / 10)
            parts.append("█" * filled + "░" * (10 - filled))
            parts.append(f"{pct:>3.0f}%")
        parts.append(f"{now - st['started']:>5.0f}s")
        out.append(" ".join(parts))
    return out


def _erase_block() -> None:
    """把游标移到面板顶部，并清掉它下面的一切。"""
    global _block_lines
    if _block_lines:
        sys.stdout.write(f"\033[{_block_lines}A\033[J")


def _draw_block() -> None:
    global _block_lines
    lines = _block_render()
    for ln in lines:
        sys.stdout.write(ln + "\n")
    _block_lines = len(lines)
    sys.stdout.flush()


def _redraw() -> None:
    if not _tty:
        return
    try:
        _erase_block()
        _draw_block()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #

def _hooked_print(*args, **kwargs):
    if not args or not str(args[0]).strip():
        _original_print(*args, **kwargs)      # 分隔空行不记录
        return

    msg = " ".join(str(a) for a in args)
    arxiv_id = current_task()
    stamp = datetime.now().strftime("%H:%M:%S")
    prefix = f"{stamp}  {arxiv_id} ▸ " if arxiv_id else f"{stamp} ▸ "

    # 日志行要在状态面板之上输出：先让开面板，打印，再把面板画回去。
    if _tty:
        try:
            _erase_block()
        except Exception:
            pass

    for ln in msg.split("\n"):            # 多行（异常堆栈）逐行加前缀
        line = prefix + ln
        _original_print(line, flush=kwargs.get("flush", False))
        _append(line, arxiv_id)

    if _tty:
        _draw_block()


def _append(line: str, arxiv_id: str | None) -> None:
    with _lock:
        if _merged_file is not None:
            try:
                _merged_file.write(line + "\n")
                _merged_file.flush()
            except Exception:
                pass
        if arxiv_id:
            fh = _task_file(arxiv_id)
            if fh is not None:
                try:
                    fh.write(line + "\n")
                    fh.flush()
                except Exception:
                    pass


def _task_file(arxiv_id: str):
    fh = _task_files.get(arxiv_id)
    if fh is not None and not getattr(fh, "closed", False):
        return fh
    if _papers_dir is None:
        return None
    try:
        _papers_dir.mkdir(parents=True, exist_ok=True)
        fh = open(_papers_dir / f"{arxiv_id}.log", "a", encoding="utf-8")
        _task_files[arxiv_id] = fh
        return fh
    except Exception:
        return None


def _close_task_file(arxiv_id: str) -> None:
    with _lock:
        fh = _task_files.pop(arxiv_id, None)
    if fh is not None:
        try:
            fh.close()
        except Exception:
            pass


def _banner(arxiv_id: str, text: str) -> None:
    """任务边界横幅。完整日期只在这里出现。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = f"──── {arxiv_id} {text} · {now} ────"
    if _tty:
        try:
            _erase_block()
        except Exception:
            pass
    _original_print(raw, flush=True)
    _append(raw, arxiv_id)
    if _tty:
        _draw_block()


def uninstall() -> None:
    """还原内置 print（测试用）。"""
    global _installed, _block_lines, _tty
    if _tty:
        try:
            _erase_block()
        except Exception:
            pass
    builtins.print = _original_print
    _installed = False
    _tty = None
    _block_lines = 0
