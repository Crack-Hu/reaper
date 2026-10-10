# Reference-implementation report: little-alphaxiv vs alphaxiv-open

Clones (depth 1) in `ref_repo/_research/`: `little-alphaxiv` @ `439ece4`, `alphaxiv-open` @ `f3494fc`.

## A. little-alphaxiv (16.4k LOC Python, ~7.6k LOC TS frontend)

### A1. Paper text ingestion — browser, not server

pdf.js in the browser extracts text; the backend ships **no PDF library at all** (`backend/requirements.txt`). `frontend/src/lib/extract.ts:13-30` walks pages and emits page markers (`extract.ts:27`: `` pages.push(`--- Page ${i} ---\n${lines.join("\n")}`) ``) so page anchors survive into the prompt. Two-layer cache:

- Server-global SQLite `paper` table (`backend/app/models.py:123-139`, `full_text` can be MBs), written by `PUT /api/papers/{id}` (`backend/app/routers/papers.py:71`); the browser calls it right after extraction (`frontend/src/views/PaperView.tsx:177`).
- Private uploads/Zotero imports go to `user_paper_upload` (`models.py:150-170`); the global row keeps `full_text=NULL` so paywalled text never leaks (`papers.py:60-70`).
- PDF bytes: content-addressed disk cache + range-supporting proxy (`backend/app/routers/pdf.py:34-45`).

**The model receives the whole paper, unchunked, in the system prompt** — `PaperView.tsx:187`:

```ts
PAPER_SYSTEM_PREAMBLE(arxivId!) + `\n\n=== PAPER FULL TEXT ===\n${fullText}\n=== END ===`
```

No RAG, no embeddings. Long-paper safety = truncating *history*, never the paper: `contextBudget.ts:219` `truncateToFit` counts `systemPrompt` as "a FIXED, un-droppable prefix — always counted, never truncated"; it drops whole tool-call groups from the front (`contextBudget.ts:189-211`) and if the system prompt alone busts the budget it sends anyway (`contextBudget.ts:232`). A context ring warns at 80%/95% (`contextBudget.ts:327`), calibrated against real `usage.prompt_tokens` (`llm.ts:132`).

### A2. Prompt construction

System prompt = preamble + full text, injected as the first message (`frontend/src/lib/llm.ts:47-48`). Paper preamble, `PaperView.tsx:350-354`:

> "You are a research assistant helping the user read and understand the paper {id}. … The full text of the paper is provided below. Answer questions about its content - methods, datasets, results, limitations, related work - grounded in the provided text. If the user asks something not covered in the paper, say so."

General chat has its own template (`frontend/src/views/ChatView.tsx:18-38`). Style presets append a modifier (`ChatPanel.tsx:387`; text in `types.ts:164-195`). Ask-about-selection is an ordinary user message with the excerpt quoted and page-labelled (`selectedTextAskAi.ts:34-44`).

### A3. Citation / reference handling — nothing

No reference extraction, no citation graph, no fetch-by-id tool (grep for `citation|references|bibliograph` yields unrelated hits only). The nearest affordance: search tools plus the "unfetchable" card — a paywalled/off-arXiv cited work gets a DOI-derived card with Upload Local PDF / Import from Zotero / Open source page buttons (`paperSource.ts:29-46`, `117-122`). This is the gap Reaper would be filling, not borrowing.

### A4. Tool calling

Four OpenAI-style function tools defined client-side in `paperSource.ts:126-225`: `search_arxiv` (always), `web_search` (anysearch MCP, on by default), `search_openalex`, `search_semantic_scholar` (opt-in). Descriptions are prescriptive about UI outcomes, e.g. `paperSource.ts:157-166`: "Use it as a FALLBACK … Each result surfaces as a paper card the user can act on …". The **loop runs in the browser** (`llm.ts:29-32`): stream → on `tool_calls` call `/api/search|/api/websearch` → push `{role:"tool", content: JSON.stringify(res.results.slice(0, 8))}` → re-stream; hard cap `if (++guard > 6) break` (`llm.ts:114`). Orphan tool results are repaired before each send (`llm.ts:50-58`). Payloads are capped at 8 records — the main token control on discovery.

### A5. Zotero (most relevant to you)

Three backends proxied by `backend/app/routers/zotero.py:1-25`: local `127.0.0.1:23119` (read-only `/api/users/0/...` + `/connector/saveItems|saveAttachment`), web `api.zotero.org` with `Zotero-API-Key`.

- **Import, local-first**: GET `/api/users/0/items/{key}/file`, follow the `302 → file://`, read bytes off disk; Docker storage-dir rewrite + `..` traversal guard; cloud S3 download only as fallback (`zotero.py:1238-1310`). Reverse-import endpoint `POST /paper-upload/import-from-zotero` (`paper_uploads.py:206`) dedups per user by sha256.
- **Write**: `POST /zotero/save-arxiv` (`zotero.py:1018`) builds a `preprint` item (archiveID, shortTitle, `extra: arXiv: <id>`, `zotero.py:868-908`), attaches the PDF via the two-step connector (`zotero.py:982-1013`); child notes only in web mode.
- **Annotation → note sync**: web-only and continuous. Tagged child note (`zoteroNote.ts:12`) rendered from annotations (`zoteroNote.ts:135-186`), PATCHed with `If-Unmodified-Since-Version` (`zotero.py:692-728`), skipped when an FNV content signature is unchanged (`zoteroNote.ts:189-210`), polled every 45 s (`useZoteroNoteSync.ts:34,205`). Creds are Fernet-encrypted in `user_settings.zotero_config` (`zotero.py:1120-1135`).

### A6. Context / state management

Conversations are SQLite rows whose `messages` JSON column is rewritten whole on every mutation (`models.py:84-110`; `conversations.py:1-7`), with branching lineage fields. No summarization — only history truncation and an LLM-generated conversation title (`llm.ts:339-400`). No vector store.

## B. alphaxiv-open (~1.3k LOC — instructive by contrast)

- **Server-side ingestion**: download PDF (`arxiv_service.py:74-128`) → markitdown → one `.md` (`markdown_service.py:29-45`) → whole markdown POSTed to a LightRAG/MiniRAG HTTP server, `POST localhost:9721/documents/text` (`indexing_service.py:123`); retrieval is `POST /query {mode:"hybrid"}`, top_k 10 (`indexing_service.py:225-229`).
- **Prompt**: a single f-string in `gemini_service.py:95-118` ("You are an AI assistant that helps users understand academic papers…"), chunks injected as "Context 1: …". No system role, no history, no streaming.
- **No tools, no citations, no Zotero, no annotations, no persistence** (grep: zero hits). The frontend holds messages in `useState`; `/api/chat` is stateless.
- Two defects to avoid: `/query` carries **no document filter** (the saved `document_id.txt` is never sent), so retrieval spans every indexed paper; and `start_minirag.py:27` defaults to port **9621** while every caller uses **9721**, so the shipped default silently degrades to keyword-over-paragraphs retrieval (`indexing_service.py:265-285`).

## Portable ideas for Reaper

1. Page-marked text (`--- Page N ---`) as the system-prompt prefix — cheap "where is this said" grounding, fits your bilingual HTML pipeline.
2. Global dedup cache keyed by arXiv id, with a separate per-user private row for paywalled/Zotero content (`papers.py:60-70`).
3. System prompt assembled per request, un-droppable; history truncated in tool-group-atomic units (`contextBudget.ts:189-260`).
4. Tool loop with a hard round cap, 8-result payloads, and repaired orphan tool messages.
5. Zotero local-first: `/api/users/0/items/{key}/file` + `file://` redirect, `Host: 127.0.0.1:23119` spoof (Zotero rejects other Hosts), storage-dir rewrite + traversal guard.
6. Annotation→note sync: tag for rediscovery, `If-Unmodified-Since-Version` on PATCH, content signature to skip no-op writes, interval polling.
7. Context-usage indicator calibrated from real `prompt_tokens` instead of a tokenizer.

## Overkill / avoid

- Browser-side tool loop and prompt assembly — fine for their SPA, wrong for a CLI + local server; run the loop server-side and reuse the message shapes.
- Per-user auth/Fernet/SMTP/alembic stack (`security.py`, `email.py`) if Reaper stays localhost-only.
- Whole-array `PUT /conversations/{id}` per mutation — acceptable at their scale; use append-only messages.
- No citation layer at all — do not copy "let the model search again" for referenced works.
- alphaxiv-open's MiniRAG graph: a second server, OpenAI embeddings, per-paper index dirs, and no scoping. For one paper at a time, full text in context beats it; for very long papers/reference corpora use scoped chunks, not LightRAG.
- markitdown + Gemini + global graph: three extra failure modes for little gain in a Zotero-centric CLI.
