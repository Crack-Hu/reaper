"""术语字典 — 双层结构：用户手动定义 + LLM 自动提取

并发安全
--------
翻译是并发的，而术语表是共享的可变状态，所以这里做了三件事：

1. **进程内锁**（``_lock``）—— 同一个服务器进程里的多个翻译线程不会互相覆盖。
2. **落盘前合并**（read-merge-write）—— 写之前先从磁盘重读，把别的实例
   新加的术语合并进来，再写回。这解决了「两个 TermDictionary 实例各持一份
   内存副本，后写的覆盖先写的」导致的丢更新。
3. **原子写入**（临时文件 + ``os.replace``）—— 读方永远看不到写了一半的
   JSON，避免解析失败。

局限：跨进程仍然是「合并后覆盖」，不是真正的事务。服务器进程是主要的写入方，
CLI 偶尔并发写入时最坏情况是丢掉最后一条术语，文件不会损坏。
"""

import json
import os
import threading
from .. import config

# 按字典目录共享的锁。术语表的并发问题不是「一个实例内的线程」，而是
# 「多个实例各持一份内存副本」，所以锁必须跨实例共享才能让落盘前的合并真正生效。
_path_locks: dict[str, threading.RLock] = {}
_path_locks_guard = threading.Lock()


def _lock_for(base_dir: str) -> threading.RLock:
    """返回某个字典目录对应的进程内共享锁。"""
    with _path_locks_guard:
        lock = _path_locks.get(base_dir)
        if lock is None:
            lock = threading.RLock()
            _path_locks[base_dir] = lock
        return lock


class TermDictionary:
    """双层术语表。

    用户定义 (``dict/user_terms.json``) — 高优先级，手动管理
    LLM 提取 (``dict/llm_terms.json``)  — 低优先级，翻译时自动追加

    给 LLM 时用 ``flattened`` 属性平铺，用户定义覆盖 LLM。
    """

    def __init__(self, dict_path: str | None = None):
        base = os.path.dirname(dict_path or config.DEFAULT_DICT_PATH)
        os.makedirs(base, exist_ok=True)
        self._user_path = os.path.join(base, "user_terms.json")
        self._llm_path = os.path.join(base, "llm_terms.json")
        # 跨实例共享（同一目录的多个 TermDictionary 互相串行化）
        self._lock = _lock_for(base)

        self._user: dict[str, str] = {}   # 用户定义 (优先)
        self._llm: dict[str, str] = {}    # LLM 提取

        self._load(self._user_path, self._user)
        self._load(self._llm_path, self._llm)

    # ---- 磁盘 IO ----

    def _load(self, path: str, target: dict) -> None:
        """读取一个 JSON 字典。损坏或读不到时静默跳过（不能因此中断翻译）。"""
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                target.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self, path: str, source: dict) -> None:
        """原子写入：先写临时文件，再 replace 覆盖。"""
        tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(source, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _merge_from_disk(self, path: str, target: dict, *, keep: bool = True) -> None:
        """把磁盘上的内容合并进 ``target``（不覆盖已有键）。

        用于落盘前吸收其他实例/进程新增的条目。
        """
        disk: dict[str, str] = {}
        self._load(path, disk)
        for k, v in disk.items():
            if keep:
                target.setdefault(k, v)
            else:
                target[k] = v

    # ---- 平铺字典 (用户优先) ----

    @property
    def flattened(self) -> dict[str, str]:
        """合并两层，用户覆盖 LLM。"""
        with self._lock:
            merged = dict(self._llm)
            merged.update(self._user)
            return merged

    @property
    def all_terms(self) -> dict[str, str]:
        """兼容旧代码。"""
        return self.flattened

    # ---- 用户操作 ----

    def get(self, term_en: str) -> str | None:
        with self._lock:
            return self._user.get(term_en.lower()) or self._llm.get(term_en.lower())

    def set_user(self, term_en: str, term_zh: str):
        with self._lock:
            # 吸收别的实例写入的用户术语，避免覆盖
            self._merge_from_disk(self._user_path, self._user)
            self._user[term_en.lower()] = term_zh
            self._save(self._user_path, self._user)

    def delete_user(self, term_en: str):
        with self._lock:
            self._merge_from_disk(self._user_path, self._user)
            self._user.pop(term_en.lower(), None)
            self._save(self._user_path, self._user)

    # ---- LLM 自动提取 ----

    def add_llm_terms(self, pairs: dict[str, str]) -> int:
        """批量添加 LLM 提取的术语。已存在的（用户或 LLM）跳过。

        返回实际新增数量。
        """
        with self._lock:
            # 关键：先吸收磁盘上别的实例新增的术语，再做增量判断。
            # 否则「后写覆盖先写」会丢掉并发翻译积累的术语。
            self._merge_from_disk(self._llm_path, self._llm)

            existing = self.flattened
            added = 0
            for en, zh in pairs.items():
                key = en.lower().strip()
                if key and key not in existing and len(key) >= 3:
                    self._llm[key] = zh.strip()
                    added += 1
            if added:
                self._save(self._llm_path, self._llm)
                print(f"    +{added} LLM terms saved to {os.path.basename(self._llm_path)}")
            return added

    def save(self):
        with self._lock:
            self._save(self._user_path, self._user)
            self._merge_from_disk(self._llm_path, self._llm)
            self._save(self._llm_path, self._llm)

    def __len__(self):
        return len(self.flattened)

    def __repr__(self):
        with self._lock:
            return (f"<TermDict user={len(self._user)} llm={len(self._llm)} "
                    f"total={len(self.flattened)}>")
