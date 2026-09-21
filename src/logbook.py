"""日志：按任务分文件 + 紧凑行格式。

问题
----
多个任务并行时（不同论文的生成/对话），所有输出混在同一个文件里交错，
无法跟读任何单个任务。而且每行都带完整日期，噪音大。

方案
----
1. **线程局部任务上下文** —— 每个 HTTP 请求跑在自己的线程里，所以日志器
   能自动知道当前在处理哪篇论文，不必把 ``arxiv_id`` 穿过每一层调用
   （fetcher / translator / renderer 都直接 ``print()``）。
2. **每个任务一份日志** ``logs/papers/{arxiv_id}.log`` —— ``tail -f`` 即可
   干净地跟读单篇论文，完全不交错。合并日志仍然保留，作为全局时间线。
3. **紧凑行格式** —— ``HH:MM:SS  2210.00921 ▸ 消息``；完整日期只在任务
   开始/结束的横幅上出现一次，正是它该出现的地方。

用法
----
    import logbook
    logbook.configure(config.LOG_DIR)          # 装好 print 钩子

    with logbook.task("2210.00921"):           # 标记当前线程在跑哪个任务
        print("...")                           # 自动带上标签并分流
"""

from __future__ import annotations

import builtins
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_ctx = threading.local()
_lock = threading.Lock()
_merged_file = None
_papers_dir: Path | None = None
_task_files: dict[str, object] = {}
_original_print = builtins.print
_installed = False


def configure(log_dir: str, papers_subdir: str = "papers") -> None:
    """安装 print 钩子并打开合并日志。可重复调用（幂等）。"""
    global _merged_file, _papers_dir, _installed
    if _installed:
        return

    log_path = Path(log_dir) / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _merged_file = open(str(log_path), "a", encoding="utf-8")
    _papers_dir = Path(log_dir) / papers_subdir

    builtins.print = _hooked_print
    _installed = True


def merged_log_path() -> str | None:
    return getattr(_merged_file, "name", None)


def task_log_path(arxiv_id: str) -> str | None:
    if _papers_dir is None:
        return None
    return str(_papers_dir / f"{arxiv_id}.log")


# --------------------------------------------------------------------------- #
# task context
# --------------------------------------------------------------------------- #

def current_task() -> str | None:
    """当前线程正在处理的 arxiv_id，没有则 None。"""
    return getattr(_ctx, "arxiv_id", None)


@contextmanager
def task(arxiv_id: str):
    """把当前线程标记为在处理 ``arxiv_id``，并给它开一份独立日志。"""
    previous = getattr(_ctx, "arxiv_id", None)
    _ctx.arxiv_id = arxiv_id
    _banner(arxiv_id, "开始", fg="\033[1;36m" if _tty() else "", bg="")
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        _banner(arxiv_id, f"结束（{elapsed:.1f}s）", fg="\033[1;36m" if _tty() else "", bg="")
        _ctx.arxiv_id = previous
        _close_task_file(arxiv_id)


def _tty() -> bool:
    try:
        return os.isatty(1)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #

def _hooked_print(*args, **kwargs):
    """替代内置 print：加标签、分流到任务日志，空行原样透传。"""
    if not args or not str(args[0]).strip():
        _original_print(*args, **kwargs)      # 分隔空行不记录
        return

    msg = " ".join(str(a) for a in args)
    arxiv_id = current_task()
    stamp = datetime.now().strftime("%H:%M:%S")
    prefix = f"{stamp}  {arxiv_id} ▸ " if arxiv_id else f"{stamp} ▸ "

    # 多行消息（异常堆栈、API 原始响应）逐行加前缀，否则只有首行可识别、
    # 而且会把整块当成一行写进日志。
    for ln in msg.split("\n"):
        line = prefix + ln
        _original_print(line, flush=kwargs.get("flush", False))
        _append(line, arxiv_id)


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
    """每篇论文一个追加写入的文件句柄（按需打开并缓存）。"""
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


def _banner(arxiv_id: str, text: str, fg: str = "", bg: str = "") -> None:
    """任务边界横幅。完整日期只在这里出现。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = f"──── {arxiv_id} {text} · {now} ────"
    _original_print(f"{fg}{raw}\033[0m" if fg else raw, flush=True)
    _append(raw, arxiv_id)


# --------------------------------------------------------------------------- #
# convenience for non-task messages
# --------------------------------------------------------------------------- #

def note(msg: str) -> None:
    """记录一条与具体论文无关的消息（服务器启动、状态变更等）。"""
    print(msg)


def uninstall() -> None:
    """还原内置 print（测试用）。"""
    global _installed
    builtins.print = _original_print
    _installed = False
