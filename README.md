# Reaper

把 arXiv 论文变成**中英对照的可读 HTML**（作为 Zotero 附件），并在此基础上做
**围绕论文与 AI 的对话**。

**架构铁律：pi 是引擎，Reaper 只是 UI。** LLM 调用、工具循环、会话管理、上下文
压缩全部由 `pi --mode rpc` 子进程承担；本仓库只做论文数据准备、通信桥和界面。

## 状态

| 部分 | 状态 |
|---|---|
| 论文生成线（获取 → 解析 → 翻译 → 渲染 → Zotero 附件） | ✅ 可用 |
| 对话后端（pi 桥 / 会话 / SSE API / 论文工作区） | ✅ 可用（分支 `feat/chat-panel`） |
| **Zotero 对话面板** | 🚧 **下一步** → `zotero-plugin/README.md` |
| 选中段落提问 / 引用解析 | 🔲 计划 → `CHAT_PLAN.md` |

## 快速开始

```bash
pip3 install -r requirements.txt      # 依赖只有 httpx
python3 src/server.py                 # 后端 → http://localhost:16625
python3 main.py 2401.04268            # CLI：单篇论文全流程
bash zotero-plugin/setup.sh           # 打包并安装 Zotero 插件（重启 Zotero 生效）
```

对话链路手工验证：

```bash
curl -s -X POST localhost:16625/api/chat/prepare \
     -H 'Content-Type: application/json' -d '{"arxiv_id":"2210.00921"}'
open http://127.0.0.1:16625/api/chat/prototype     # 测试页
```

## 文档地图

| 文档 | 内容 |
|---|---|
| `AGENTS.md` | Agent 入口：硬性约束 + 文档索引（pi 自动加载） |
| `HANDOFF.md` | **当前交接**：状态、模块地图、下一步、坑、约定 |
| `ARCHITECTURE.md` | 架构参考：两条链路、协议、API 总表、数据模型 |
| `CHAT_PLAN.md` | 对话功能的调研与设计记录（讨论稿） |
| `roadmap.md` | 最初的四阶段路线图（历史文档） |
| `src/chat/README.md` 等 | 模块说明（chat / ingestion / translation / rendering） |
| `zotero-plugin/README.md` | 插件说明 + **对话面板实现指南** |
| `prototype/README.md` | 测试页用法 + 移植映射 |
| `tests/README.md` | 测试现状（部分用例按旧 API 写的，跑之前先读） |
| `docs/` | 竞品与参考实现调研报告 |

## 目录

```
src/            后端：server / config / task / logbook + ingestion / translation / rendering / chat
zotero-plugin/  Zotero 插件
pi-extensions/  pi 扩展（补 RPC 缺失命令：/goto /label /where）
prototype/      对话后端测试页（chat.html）
tests/          测试套件
tools/          一次性脚本（数据迁移）
data/           运行时产物（gitignore）
```

## 注意

- 论文正文是**不可信输入**：agent 工具白名单保持只读（`read,grep,find,ls`）。
- 聊天端点默认**仅回环**可访问（agent 能读文件）。
- `config.json` 含真实 API key（gitignore），不要提交。
- 每次修改正常 `git commit`，不要 squash / `git reset --soft` 覆盖历史。
