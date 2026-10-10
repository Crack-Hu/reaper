# src — 服务端代码

| 路径 | 说明 |
|---|---|
| `server.py` | HTTP 后端（`ThreadingHTTPServer`）：论文生成流水线 + 挂载 `/api/chat/*` |
| `cli.py` | 命令行入口（`python3 main.py <arxiv-id>`） |
| `config.py` | 配置 + **数据路径的唯一来源**（`source_dir()` / `process_dir()` / `chat_*_dir()` …） |
| `task.py` | 翻译任务状态机，支持断点续传（`state.json`，`error_history` 保留最近 10 条） |
| `logbook.py` | 并发日志：终端状态面板（原地重绘）+ 每论文独立日志文件 |
| `ingestion/` | 多来源获取 + 解析为 `Block` → `ingestion/README.md` |
| `translation/` | 按章节翻译 + 术语表 + 缓存 → `translation/README.md` |
| `rendering/` | 双语 HTML 渲染 → `rendering/README.md` |
| `chat/` | 与 pi 对话的桥/会话/API → `chat/README.md` |

## 路径与数据布局

**新增代码一律用 `config.py` 里的函数取路径，不要手拼字符串。** 当前布局：

```
data/papers/{arxiv_id}/{source,process,chat}   # 见 config.py 头部注释
```

`config.py` 底部有一组**向后兼容别名**（`CACHE_DIR`、`ZOTERO_DIR` 等）指向旧布局，
新代码不要使用它们。

## 日志

`logbook.configure(config.LOG_DIR)` 在 server 启动时调用一次。
在任务内用 `with logbook.task(arxiv_id):` 包住整段流水线：期间所有 `print`
都会加上论文前缀并同时写 `logs/papers/{id}.log`；`logbook.set_progress(phase=..., pct=...)`
更新终端状态面板。

## 约定

- 错误信息面向用户排障，要带可操作提示（例如插件端会原样显示 server 的 JSON error）。
- 并发写文件：小文件用「锁 + 临时文件 + `os.replace`」；不要在持有锁时做网络请求。
