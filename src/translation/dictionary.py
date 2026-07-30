"""术语字典 — 双层结构：用户手动定义 + LLM 自动提取"""

import json
import os
from .. import config


class TermDictionary:
    """双层术语表。
    用户定义 (dict/user_terms.json) — 高优先级，手动管理
    LLM 提取 (dict/llm_terms.json)  — 低优先级，翻译时自动追加
    给 LLM 时用 flattened 属性平铺，用户覆盖 LLM。
    """

    def __init__(self, dict_path: str | None = None):
        base = os.path.dirname(dict_path or config.DEFAULT_DICT_PATH)
        os.makedirs(base, exist_ok=True)
        self._user_path = os.path.join(base, "user_terms.json")
        self._llm_path = os.path.join(base, "llm_terms.json")

        self._user: dict[str, str] = {}   # 用户定义 (优先)
        self._llm: dict[str, str] = {}    # LLM 提取

        self._load(self._user_path, self._user)
        self._load(self._llm_path, self._llm)

    def _load(self, path, target):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                target.update(json.load(f))

    def _save(self, path, source):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(source, f, ensure_ascii=False, indent=2)

    # ---- 平铺字典 (用户优先) ----

    @property
    def flattened(self) -> dict[str, str]:
        """合并两层，用户覆盖 LLM。"""
        merged = dict(self._llm)
        merged.update(self._user)
        return merged

    @property
    def all_terms(self) -> dict[str, str]:
        """兼容旧代码。"""
        return self.flattened

    # ---- 用户操作 ----

    def get(self, term_en: str) -> str | None:
        return self._user.get(term_en.lower()) or self._llm.get(term_en.lower())

    def set_user(self, term_en: str, term_zh: str):
        self._user[term_en.lower()] = term_zh
        self._save(self._user_path, self._user)

    def delete_user(self, term_en: str):
        self._user.pop(term_en.lower(), None)
        self._save(self._user_path, self._user)

    # ---- LLM 自动提取 ----

    def add_llm_terms(self, pairs: dict[str, str]):
        """批量添加 LLM 提取的术语。已存在的（用户或 LLM）跳过。"""
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

    def save(self):
        self._save(self._user_path, self._user)
        self._save(self._llm_path, self._llm)

    def __len__(self):
        return len(self.flattened)

    def __repr__(self):
        return f"<TermDict user={len(self._user)} llm={len(self._llm)} total={len(self.flattened)}>"
