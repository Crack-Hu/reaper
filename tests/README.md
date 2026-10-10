# tests — 测试套件

## 运行

```bash
cd /Users/crack/Crack/pi-extension/reaper
python3 tests/run_tests.py
```

## ⚠️ 当前状态：部分失效（按旧 API 写的）

`run_tests.py` 的部分用例仍按 **FetchedPage 重构之前**的 API 编写，直接跑会在这些类
报 `TypeError`。已知可用/失效情况：

| 组 | 状态 | 说明 |
|---|---|---|
| `TestArxivIDExtraction` | ✅ 通过 | 纯单元 |
| `TestPaperCacheV2` | ✅ 通过 | 纯单元（用 9999.99999 临时缓存） |
| `TestErrorRecovery` | ⚠️ 空转 | 断言是「抛任意异常」，旧 API 的 TypeError 也能让它过——等于没有验证 |
| `TestTranslationWithMock` | ❌ 失效 | `arxiv_id, src_type, raw = fetch_html(...)` → FetchedPage 不可解包 |
| `TestImageCaching` / `TestInlineImageFallback` | ⚠️ 待核 | 依赖内部函数签名 |
| `TestFetchAr5iv` / `TestFetchArxivHTML` | ❌ 失效 | 同上，旧元组解包 API |
| `TestParseRealHTML` | ⚠️ 待核 | 依赖已缓存 HTML |
| `TestRenderLightMode` / `TestRenderFullMode` / `TestRenderArxivHTMLSource` | ❌ 失效 | `render_bilingual_html(..., arxiv_id=, source_type=)` 参数已被 `fp: FetchedPage` 取代 |
| `TestGeneratePaperFlow` | ❌ 失效 | 依赖上面的旧调用 |

**修复方向**（一次足以恢复大部分）：

```python
fp = fetch_html("2307.14989", cache_dir=tmp)          # FetchedPage
marked, blocks = mark_and_extract(fp.html)
fake = [{"zh": "", "type": b.type, "math_map": b.math_map} for b in blocks]
html = render_bilingual_html(marked, fake, fp, embed_images=False)
```

`gen_3sources.py <arxiv-id>`（三来源渲染对比脚本）同样按旧 API 写的，目前不可用。

## 版本管理

本目录已纳入 git（2026-10-10 起不再被 `.gitignore` 忽略）；`__pycache__/` 由全局规则忽略。
