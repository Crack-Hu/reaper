# src/translation — 翻译引擎

按章节并发调用 LLM 翻译，维护双层术语表，按段落缓存结果。

## 文件

| 文件 | 职责 |
|---|---|
| `translator.py` | prompt 组装、LLM 调用、章节分组/拆分、并发调度、编号对齐 |
| `dictionary.py` | `TermDictionary`：用户术语（高优先）+ LLM 自动提取（低优先） |
| `cache.py` | `PaperCache` v2：HTML hash + blocks + 译文，一个文件存全流程状态 |

## 翻译流程（默认按章节）

```
blocks[] → group_blocks_by_section()   按 section 标题分组
         → 超过 10000 字符的节在段落边界平衡拆分
         → 每节一个任务提交全局 ThreadPoolExecutor（translator.concurrency）
         → prompt = 论文标题 + 摘要 + 术语表 + REAPER_PARA_N 编号的段落
         → LLM 返回编号译文 → 按编号回填（不依赖数量一致）
```

- **prompt 中的段落编号 `REAPER_PARA_N` 是唯一对齐方式**。LLM 少输出/合并输出都不会串段。
- 标题（title/section）走 inline 翻译；`<10` 字符的块和 `figure/table/equation` 跳过。
- `batch_size > 0` 是历史遗留的固定批量模式，默认走章节模式。
- 服务端传入共享 executor 与 `on_progress` 回调，进度由 `src/logbook.py` 渲染。

## LLM 调用（`call_llm_api`）

- 兼容 OpenAI `/chat/completions`；`config.LLM_PARAMS` **原样透传**（如 `reasoning_effort: none`）。
- 端点若返回 400（不认这些参数）→ **自动去掉 params 重试一次**。
- 推理模型的 reasoning token 也算在 `max_tokens` 里：给太小会出现
  `content: null` + `finish_reason: length`（已修：模板默认 16384）。
- 重试：`TRANSLATION_MAX_RETRIES`（默认 3）。

## 术语表（dictionary.py）

```
data/dict/user_terms.json   用户手动定义，高优先级
data/dict/llm_terms.json    翻译时自动提取，低优先级
```

并发安全三板斧（翻译是多线程的）：

1. 进程内**跨实例**共享锁（问题不是单实例内的线程，而是多实例各持一份内存副本）；
2. 落盘前 **read-merge-write**（先重读磁盘再合并写回，避免后写覆盖先写）；
3. **原子替换**（临时文件 + `os.replace`），读方永远看不到半份 JSON。

局限：跨进程仍是「合并后覆盖」，最坏丢最后一条术语，文件不会损坏。

## 缓存（cache.py）

`PaperCache` 存在 `process/translation_cache/cache.json`：

```json
{"version": 2, "html_hash": "...", "src_type": "ar5iv", "blocks": [
  {"idx": 0, "hash": "段落 sha256 前 16 位", "en": "...", "zh": "...",
   "type": "para", "level": 0, "label": "", "math_map": {}}
]}
```

- `match(html)` 成立时 server 可**跳过解析和翻译**，直接 `restore()`。
- HTML 变了也能按段落 hash 复用旧译文（部分命中）。
- v1 旧格式（`{hash: zh}` 平铺）自动识别并迁移。
- 变更后**必须** `save()`；server 只在 `merge_translations()` 之后保存，
  避免崩溃时落盘一份 0 翻译的缓存。

## 测试

`tests/run_tests.py` 里的 `TestPaperCacheV2`、`TestTranslationWithMock`（mock LLM）。
