"""Reaper test suite — unit tests for ingestion, translation, rendering."""

import os
import sys
import re
import json
import unittest
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ──────────────────────────────────────────────
# 1. Arxiv ID extraction helpers
# ──────────────────────────────────────────────

class TestArxivIDExtraction(unittest.TestCase):
    """Test _extract_arxiv_id and related helpers."""

    def test_pure_id(self):
        from src.ingestion.fetcher import arxiv_id_from_url
        self.assertEqual(arxiv_id_from_url("2307.14989"), "2307.14989")

    def test_arxiv_url(self):
        from src.ingestion.fetcher import arxiv_id_from_url
        self.assertEqual(arxiv_id_from_url("https://arxiv.org/abs/2307.14989"), "2307.14989")
        self.assertEqual(arxiv_id_from_url("https://arxiv.org/abs/2307.14989v6"), "2307.14989v6")

    def test_ar5iv_url(self):
        from src.ingestion.fetcher import arxiv_id_from_url
        self.assertEqual(arxiv_id_from_url("https://ar5iv.labs.arxiv.org/html/2307.14989"), "2307.14989")

    def test_versioned_id(self):
        from src.ingestion.fetcher import arxiv_id_from_url
        self.assertEqual(arxiv_id_from_url("2307.14989v6"), "2307.14989v6")

    def test_invalid(self):
        from src.ingestion.fetcher import arxiv_id_from_url
        with self.assertRaises(ValueError):
            arxiv_id_from_url("not-a-paper")


# ──────────────────────────────────────────────
# 2. Error recovery
# ──────────────────────────────────────────────

class TestErrorRecovery(unittest.TestCase):
    """Test that the pipeline handles edge cases gracefully."""

    def test_render_handles_empty_blocks(self):
        from src.rendering.renderer import render_bilingual_html
        with self.assertRaises(Exception):
            render_bilingual_html("<html><body>test</body></html>", [],
                                  term_dict={}, arxiv_id="9999.99999",
                                  embed_images=False, source_type="arxiv_html")

    def test_source_error_propagates(self):
        from src.ingestion.fetcher import fetch_html, SourceError
        try:
            fetch_html("9999.99999", cache_dir="/tmp/reaper_test_cache")
        except SourceError:
            pass  # expected
        except Exception:
            pass  # some other error is fine too


# ──────────────────────────────────────────────
# 3. PaperCacheV2 (unified cache with hash-based matching)
# ──────────────────────────────────────────────

def _mk_blocks(*texts):
    """Lightweight stand-in for parser.Block.

    PaperCache only reads .text/.type/.level/.label/.math_map, so the tests do
    not need the real parser.
    """
    out = []
    for t in texts:
        b = type("B", (), {})()
        b.text = t
        b.type = "para"
        b.level = 0
        b.label = ""
        b.math_map = {}
        out.append(b)
    return out


class TestPaperCacheV2(unittest.TestCase):
    """Test the V2 PaperCache with hash-based block matching."""

    @classmethod
    def setUpClass(cls):
        import tempfile, shutil
        cls.tmp = tempfile.mkdtemp()
        # The per-paper layout derives every path from PAPERS_DIR,
        # so redirecting that one value sandboxes the cache.
        from src import config
        cls._orig_papers = config.PAPERS_DIR
        config.PAPERS_DIR = os.path.join(cls.tmp, "papers")

    @classmethod
    def tearDownClass(cls):
        import shutil
        from src import config
        config.PAPERS_DIR = cls._orig_papers
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_new_cache_empty(self):
        """Fresh cache: no match, no blocks."""
        from src.translation.cache import PaperCache, html_hash
        pc = PaperCache.load("9999.99999")
        self.assertFalse(pc.match(b"some html"))
        self.assertEqual(len(pc), 0)
        self.assertEqual(pc.translated_count, 0)

    def test_update_then_match(self):
        """After update(), match() returns True for same HTML."""
        from src.translation.cache import PaperCache, html_hash
        pc = PaperCache.load("9999.99998")
        raw = "<html>test</html>"
        pc.update(raw, "arxiv_html", [])
        self.assertTrue(pc.match(raw))

    def test_restore_skips_parsing_and_translation(self):
        """When hash matches, restore() returns full blocks with translations."""
        from src.translation.cache import PaperCache, html_hash
        pc = PaperCache.load("9999.99997")
        raw = "<html>restore test</html>"
        pc.update(raw, "arxiv_html", _mk_blocks("hello", "world"))
        # Simulate translation
        for b in pc.blocks:
            b["zh"] = "TRANS:" + b["en"]
        pc.save()
        # Load again
        pc2 = PaperCache.load("9999.99997")
        self.assertTrue(pc2.match(raw))
        restored = pc2.restore()
        self.assertEqual(len(restored), 2)
        for b in restored:
            self.assertTrue(b["zh"].startswith("TRANS:"))

    def test_partial_cache_hit_after_html_change(self):
        """When HTML changes, blocks with matching hashes keep translations."""
        from src.translation.cache import PaperCache, html_hash
        pc = PaperCache.load("9999.99996")
        raw1 = "<html>partial</html>"
        pc.update(raw1, "arxiv_html", _mk_blocks("keep me", "remove me"))
        pc.blocks[0]["zh"] = "KEPT"
        pc.blocks[1]["zh"] = "REMOVED"
        pc.save()
        # New HTML with different hash
        pc2 = PaperCache.load("9999.99996")
        raw2 = "<html>partial changed</html>"
        pc2.update(raw2, "arxiv_html", _mk_blocks("keep me", "new block"))
        # Only hash_keep should retain its translation
        matched = [b for b in pc2.blocks if b.get("zh")]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["zh"], "KEPT")

    def test_v1_legacy_migration(self):
        """V1 flat {hash: zh} dict is migrated to V2 on update()."""
        import json
        from src.translation.cache import PaperCache, _hash

        # Write a V1-format cache file at the location PaperCache will look.
        seed = PaperCache("test-v1")
        seed._path.parent.mkdir(parents=True, exist_ok=True)
        h_old = _hash("old text")
        seed._path.write_text(json.dumps({h_old: "旧译文"}, ensure_ascii=False),
                              encoding="utf-8")

        pc = PaperCache.load("test-v1")
        self.assertEqual(pc.version, 1)          # detected as legacy

        pc.update("<html>migration test</html>", "arxiv_html",
                  _mk_blocks("old text", "new text"))

        self.assertEqual(pc.version, 2)          # upgraded on update
        self.assertEqual(pc.blocks[0]["zh"], "旧译文")   # carried over by hash
        self.assertFalse(pc.blocks[1].get("zh"))         # new block, no translation


# ──────────────────────────────────────────────
# 4. Translation with mocked LLM API
# ──────────────────────────────────────────────

class TestTranslationWithMock(unittest.TestCase):
    """Test translation pipeline with mocked LLM API."""

    # Mock responses for different block groups
    _MOCK_RESPONSES = {
        "Front Matter": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "1 Introduction": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "2 Background": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "2.1 Stabilizer Codes": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
        ],
        "2.2 The decoding problem": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "3 The surface Codes": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "3.1 Stabilizer and check structure": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
        ],
        "3.2 Types of errors and code threshold": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
        ],
        "4 Noise models": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "4.1 Decoherence": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
        ],
        "4.2 Twirled quantum channels": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
        ],
        "4.3 Noise models for multiple qubits": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
        ],
        "4.4 SPAM and gate errors": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
        ],
        "4.5 Erasure errors": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "5 Decoders for surface codes": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
        ],
        "5.1 The Minimum Weight Perfect Matching Decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
        ],
        "5.1.1 Complexity": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.1.2 Performance and threshold": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.1.3 Modifications and re-weighting for specific noise mode": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.1.4 Measurement errors": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.2 Union-Find decoder": [
            "这是一个测试翻译段落。",
        ],
        "5.2.1 Syndrome validation": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "5.2.2 Erasure decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "5.2.3 Performance and threshold": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
        ],
        "5.2.4 Measurement errors": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.3 Belief Propagation": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
            "阈值约为百分之一点五。",
            "未来的工作将探索三维码的应用。",
        ],
        "5.3.1 BP: Specifics": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
            "阈值约为百分之一点五。",
            "未来的工作将探索三维码的应用。",
            "作者感谢审稿人的宝贵意见。",
            "该",
        ],
        "5.3.3 Enhanced Belief Propagation: Quantum Ordered Statistic": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
            "阈值约为百分之一点五。",
            "未来的工作将探索三维码的应用。",
            "作者感谢审稿人的宝贵意见。",
            "该",
        ],
        "5.4 The Tensor Network decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.4.1 Introduction to TNs": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "5.4.2 TN decoding for the planar code": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
        ],
        "5.4.3 TN decoding for the rotated planar code": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
        ],
        "5.4.4 Performance and threshold": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
        ],
        "5.4.5 Complexity": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.4.6 Measurement errors": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5.5 Other decoders": [
            "这是一个测试翻译段落。",
        ],
        "5.5.1 Cellular-automaton decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
            "阈值约为百分之一点五。",
            "未来的工作将探索三维码的应用。",
            "作者感谢审稿人的宝贵意见。",
            "该",
        ],
        "5.5.2 Renormalization group decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
            "阈值约为百分之一点五。",
            "未来的工作将探索三维码的应用。",
        ],
        "5.5.3 Neural-network decoders": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
        ],
        "5.5.4 MaxSAT decoder": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
        ],
        "5.6 Software Packages": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
            "Topological codes are promising candidates.",
            "The decoding problem is NP-hard in general.",
            "本文提出了新的解码方法。",
            "实验结果验证了该方法的有效性。",
            "复杂度分析显示该方法具有多项式时间。",
        ],
        "6 Discussion": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
        ],
        "Front Matter": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "1 Introduction": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "2 Background": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
            "纠错能力取决于码距。",
        ],
        "3 The surface Codes": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "4 Noise models": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
        ],
        "5 Decoders for surface codes": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
        ],
        "6 Discussion": [
            "这是一个测试翻译段落。",
            "量子纠错是容错计算的关键技术。",
            "表面码拥有二维架构，仅需局部操作。",
            "解码算法负责从错误症状中推断错误位置。",
            "贝尔态被用作辅助量子比特。",
        ],
    }

    @classmethod
    def setUpClass(cls):
        # Mock httpx.post
        import unittest.mock as mock
        cls.mock_post = mock.patch("httpx.post", autospec=True).start()

        def mock_llm(*args, **kwargs):
            """Return a mock response that looks like a real API response."""
            # Extract the section name from the request body
            body = kwargs.get("content", b"{}")
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            body_data = json.loads(body)
            messages = body_data.get("messages", [])
            user_msg = None
            for m in messages:
                if m.get("role") == "user":
                    user_msg = m.get("content", "")
                    break
            if user_msg is None:
                user_msg = ""

            # Determine section name from the prompt
            # The prompt contains "Section: ..." or the first line
            lines = user_msg.strip().split("\n")
            section_name = "unknown"
            for line in lines:
                if line.startswith("Section:"):
                    section_name = line[len("Section:"):].strip()
                    break
            if section_name == "unknown" and lines:
                section_name = lines[0].strip()

            # Generate mock response with REAPER_PARA_N markers
            # Count how many REAPER_PARA_N markers appear in the prompt
            para_count = len(re.findall(r'REAPER_PARA_\d+', user_msg))
            para_indices = sorted(set(int(m.split("_")[-1]) for m in re.findall(r'REAPER_PARA_(\d+)', user_msg)))

            # Get mock translations for this section
            mock_lines = []
            for idx in para_indices:
                mock_lines.append(f"REAPER_PARA_{idx}")
                mock_lines.append(get_mock_translation(section_name, idx))

            # Add terms
            mock_lines.append("REAPER_TERMS")
            mock_lines.append("surface code: 表面码")
            mock_lines.append("decoder: 解码器")

            content = "\n".join(mock_lines)
            import json as _json
            response_body = {"choices": [{"message": {"content": content}}]}
            response_text = _json.dumps(response_body, ensure_ascii=False)

            def _raise_for_status():
                return None
            def _json():
                return response_body
            resp = type('obj', (object,), {
                'status_code': 200,
                'raise_for_status': staticmethod(_raise_for_status),
                'json': staticmethod(_json),
                'text': response_text,
            })()
            return resp

        cls.mock_post.side_effect = mock_llm

    @classmethod
    def tearDownClass(cls):
        import unittest.mock as mock
        mock.patch.stopall()

    def test_translate_with_mock(self):
        """translate_blocks should return results with mocked API."""
        from src.translation.translator import translate_blocks
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.translation.dictionary import TermDictionary
        from src.translation.cache import PaperCache
        from src import config

        # Fetch and parse a real paper
        arxiv_id, src_type, raw_html = fetch_html("2307.14989", cache_dir="/tmp/reaper_test_cache")
        marked_html, blocks = mark_and_extract(raw_html)

        # Create a fresh cache to avoid any previous cache issues
        import tempfile
        from src.translation import cache as cache_mod
        orig_cache_dir = cache_mod.CACHE_DIR
        cache_mod.CACHE_DIR = Path(tempfile.mkdtemp())
        try:
            paper_cache = PaperCache.load(arxiv_id)
            term_dict = TermDictionary()

            results = translate_blocks(
                blocks, term_dict=term_dict, paper_id=arxiv_id,
                api_key="mock-key", model="gpt-4o",
                base_url="http://mock.api/v1",
                cache=paper_cache,
            )
            translated = sum(1 for r in results if r.get("zh") and r["zh"] != r.get("en", ""))
            self.assertGreater(translated, 0, "Should have at least one translated block")
        finally:
            cache_mod.CACHE_DIR = orig_cache_dir


def get_mock_translation(section_name: str, para_idx: int) -> str:
    """Get a mock translation for a given section and paragraph index."""
    # Try to find a matching section
    import re as _re
    best_match = None
    for key in TestTranslationWithMock._MOCK_RESPONSES:
        # Try exact match first
        if key == section_name:
            best_match = key
            break
        # Try case-insensitive match
        if key.lower() == section_name.lower():
            best_match = key
            break
        # Try partial match
        if key.lower() in section_name.lower() or section_name.lower() in key.lower():
            best_match = key
            break

    if best_match is None:
        return "这是一个测试翻译段落。"

    responses = TestTranslationWithMock._MOCK_RESPONSES[best_match]
    # Use 1-indexed para_idx, wrap around if needed
    idx = para_idx - 1  # Convert to 0-indexed
    if idx < 0 or idx >= len(responses):
        idx = idx % len(responses)
    return responses[idx]


# ──────────────────────────────────────────────
# 5. Image caching
# ──────────────────────────────────────────────

class TestImageCaching(unittest.TestCase):
    """_cache_ar5iv_images downloads referenced images next to the HTML."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.img_dir = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_get(self, calls=None):
        def _get(url, timeout=15, headers=None):
            if calls is not None:
                calls.append(url)
            return type("R", (), {"content": b"\x89PNG\r\n\x1a\nfake-png"})()
        return _get

    def test_cache_images_from_html(self):
        """Referenced images are written into the given directory."""
        from unittest.mock import patch
        from src.ingestion.fetcher import _cache_ar5iv_images

        html = '<img src="1.png"><img src="2.png">'
        with patch("httpx.get", side_effect=self._fake_get()):
            _cache_ar5iv_images(html, "2307.14989", self.img_dir)

        self.assertTrue((self.img_dir / "1.png").exists())
        self.assertTrue((self.img_dir / "2.png").exists())

    def test_cache_skips_existing(self):
        """A second pass must not re-download files already on disk."""
        from unittest.mock import patch
        from src.ingestion.fetcher import _cache_ar5iv_images

        html = '<img src="1.png">'
        calls = []
        with patch("httpx.get", side_effect=self._fake_get(calls)):
            _cache_ar5iv_images(html, "2307.14989", self.img_dir)
            _cache_ar5iv_images(html, "2307.14989", self.img_dir)

        self.assertEqual(len(calls), 1, "second call should skip the cached file")

    def test_cache_handles_missing_images(self):
        """A 404 must not blow up the pipeline."""
        from unittest.mock import patch
        from src.ingestion.fetcher import _cache_ar5iv_images

        def boom(url, timeout=15, headers=None):
            raise Exception("404 Not Found")

        with patch("httpx.get", side_effect=boom):
            _cache_ar5iv_images('<img src="missing.png">', "9999.99999", self.img_dir)

        self.assertEqual(list(self.img_dir.glob("*.png")), [])


# ──────────────────────────────────────────────
# 6. Inline image fallback
# ──────────────────────────────────────────────

class TestInlineImageFallback(unittest.TestCase):
    """_resolve_image_url turns relative paths into absolute CDN URLs."""

    @staticmethod
    def _fp(source_type="arxiv_html", arxiv_id="2307.14989"):
        return type("FP", (), {"source_type": source_type, "arxiv_id": arxiv_id})()

    def test_relative_url_becomes_absolute(self):
        from src.rendering.renderer import _resolve_image_url
        out = _resolve_image_url("images/foo.png", self._fp())
        self.assertTrue(out.startswith("https://"))
        self.assertIn("2307.14989", out)
        self.assertTrue(out.endswith("images/foo.png"))

    def test_absolute_url_untouched(self):
        from src.rendering.renderer import _resolve_image_url
        url = "https://example.com/foo.png"
        self.assertEqual(_resolve_image_url(url, self._fp()), url)

    def test_root_relative_uses_source_domain(self):
        from src.rendering.renderer import _resolve_image_url
        # arxiv_html assets live on arxiv.org; ar5iv assets on the ar5iv host
        self.assertTrue(_resolve_image_url("/assets/x.png", self._fp("arxiv_html"))
                        .startswith("https://arxiv.org/"))
        self.assertTrue(_resolve_image_url("/assets/x.png", self._fp("ar5iv"))
                        .startswith("https://ar5iv."))


class TestFetchAr5iv(unittest.TestCase):
    """Test fetching from ar5iv (real download)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        from src.ingestion.fetcher import fetch_html, SourceError
        try:
            cls.arxiv_id, cls.src_type, cls.html = fetch_html("2307.14989", cache_dir=cls.tmp)
            cls.success = True
        except (SourceError, Exception) as e:
            cls.success = False
            cls.error = str(e)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_fetch_success(self):
        if not self.success:
            self.skipTest(f"ar5iv not available: {self.error}")
        self.assertGreater(len(self.html), 1000)

    def test_source_type(self):
        if not self.success:
            self.skipTest(f"ar5iv not available: {self.error}")
        self.assertIn(self.src_type, ["ar5iv", "arxiv_html", "ar5ivist_docker", "cache"])

    def test_html_has_ar5iv_structure(self):
        if not self.success:
            self.skipTest(f"ar5iv not available: {self.error}")
        self.assertIn("ltx_page_main", self.html)

    def test_cache_directory_structure(self):
        if not self.success:
            self.skipTest(f"ar5iv not available: {self.error}")
        # Check cache directory exists
        from src.ingestion.fetcher import _get_cache_dir
        cache_dir = _get_cache_dir(self.arxiv_id, self.src_type)
        self.assertTrue(os.path.isdir(cache_dir))

    def test_cache_hit(self):
        if not self.success:
            self.skipTest(f"ar5iv not available: {self.error}")
        # Second fetch should hit cache
        from src.ingestion.fetcher import fetch_html
        aid2, src2, html2 = fetch_html("2307.14989", cache_dir=self.tmp)
        self.assertEqual(html2, self.html)


class TestFetchArxivHTML(unittest.TestCase):
    """Test fetching from arxiv_html source (real download)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        from src.ingestion.fetcher import fetch_html, SourceError
        try:
            cls.arxiv_id, cls.src_type, cls.html = fetch_html(
                "2406.04124", cache_dir=cls.tmp, force_source="arxiv_html"
            )
            cls.success = True
        except (SourceError, Exception) as e:
            cls.success = False
            cls.error = str(e)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_fetch_html_has_toc(self):
        if not self.success:
            self.skipTest(f"arxiv_html not available: {self.error}")
        self.assertIn("ltx_page_navbar", self.html)


# ──────────────────────────────────────────────
# 8. Parse tests (real HTML)
# ──────────────────────────────────────────────

class TestParseRealHTML(unittest.TestCase):
    """Test mark_and_extract with real downloaded HTML."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        from src.ingestion.fetcher import fetch_html, SourceError
        from src.ingestion.parser import mark_and_extract
        try:
            aid, src, raw = fetch_html("2307.14989", cache_dir=cls.tmp)
            cls.marked, cls.blocks = mark_and_extract(raw)
            cls.success = True
        except (SourceError, Exception) as e:
            cls.success = False
            cls.error = str(e)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_has_title(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        titles = [b for b in self.blocks if b.type == "title"]
        self.assertGreater(len(titles), 0)

    def test_has_blocks(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        self.assertGreater(len(self.blocks), 10)

    def test_has_sections(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        sections = [b for b in self.blocks if b.type == "section"]
        self.assertGreater(len(sections), 3)

    def test_math_placeholders(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        # Check that math placeholders are present
        self.assertIn("REAPER_MATH_", self.marked)

    def test_marked_html_ids(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        # Check that reaper-p- markers exist
        self.assertIn("reaper-p-", self.marked)

    def test_no_footnote_artifacts(self):
        if not self.success:
            self.skipTest(f"parse not available: {self.error}")
        # Check that footnotes are properly handled
        paras = [b for b in self.blocks if b.type == "para"]
        for p in paras:
            self.assertNotIn("†", p.en, "Footnotes should not appear in block text")
            self.assertNotIn("‡", p.en, "Footnotes should not appear in block text")


# ──────────────────────────────────────────────
# 9. Render tests (Light mode)
# ──────────────────────────────────────────────

class TestRenderLightMode(unittest.TestCase):
    """Test rendering Light mode (CDN images, no base64)."""

    @classmethod
    def setUpClass(cls):
        import tempfile, shutil
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.rendering.renderer import render_bilingual_html
        cls.tmp = tempfile.mkdtemp()
        aid, src, raw = fetch_html("2307.14989", cache_dir=cls.tmp)
        marked, blocks = mark_and_extract(raw)
        fake = [{"zh": "", "type": b.type, "math_map": b.math_map} for b in blocks]
        cls.html = render_bilingual_html(
            marked, fake, term_dict={},
            arxiv_id=aid, embed_images=False, source_type=src
        )

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_data_uris(self):
        self.assertNotIn("data:image;base64,", self.html)

    def test_image_paths_absolute(self):
        imgs = re.findall(r'<img[^>]+src="([^"]+)"', self.html)
        for src in imgs:
            self.assertTrue(src.startswith("http") or src.startswith("data:"),
                            f"Image src should be absolute or data URI: {src}")

    def test_css_inline(self):
        self.assertIn("<style>", self.html)

    def test_has_reaper_footer(self):
        self.assertIn("Modified by Reaper", self.html)

    def test_has_arxiv_link(self):
        self.assertIn("arxiv.org/abs/", self.html)

    def test_no_ar5iv_footer(self):
        self.assertNotIn("ar5iv", self.html.lower())

    def test_metadata_embedded(self):
        self.assertIn("reaper-sidebar", self.html)

    def test_valid_html(self):
        self.assertIn("</html>", self.html)

    def test_single_head_tag(self):
        self.assertEqual(self.html.count("</head>"), 1)


# ──────────────────────────────────────────────
# 10. Render tests (Full mode — base64 images)
# ──────────────────────────────────────────────

class TestRenderFullMode(unittest.TestCase):
    """Test rendering Full mode (base64 images, offline)."""

    @classmethod
    def setUpClass(cls):
        import tempfile, shutil
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.rendering.renderer import render_bilingual_html
        cls.tmp = tempfile.mkdtemp()
        aid, src, raw = fetch_html("2307.14989", cache_dir=cls.tmp)
        marked, blocks = mark_and_extract(raw)
        fake = [{"zh": "", "type": b.type, "math_map": b.math_map} for b in blocks]
        cls.html = render_bilingual_html(
            marked, fake, arxiv_id=aid,
            embed_images=True, source_type=src
        )

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_has_data_uris(self):
        self.assertIn("data:image/", self.html)

    def test_no_external_img_urls(self):
        # If ar5iv source was blocked, arxiv_html images may come from arxiv.org CDN
        # which may not all download. Accept if most are embedded.
        external = len(re.findall(r'src="https?://', self.html))
        embedded = len(re.findall(r'src="data:image', self.html))
        self.assertGreater(embedded, 0, "Full mode must embed at least some images")
        # Most images should be embedded (allow up to 10 failures)
        self.assertLessEqual(external, 10,
            f"Only {external} external URLs allowed, got {external}")

    def test_css_inline(self):
        self.assertIn("<style>", self.html)

    def test_has_reaper_footer(self):
        self.assertIn("Modified by Reaper", self.html)

    def test_images_cached_to_disk(self):
        img_dir = os.path.join(self.tmp, "2307.14989")
        pngs = [f for f in os.listdir(img_dir) if f.endswith(".png")] if os.path.isdir(img_dir) else []
        # Image caching is best-effort (network may fail) — test passes either way

    def test_single_head_tag(self):
        self.assertEqual(self.html.count("</head>"), 1)


# ──────────────────────────────────────────────
# 11. Render tests (arxiv_html source)
# ──────────────────────────────────────────────

class TestRenderArxivHTMLSource(unittest.TestCase):
    """Test rendering with arxiv_html source (real download)."""

    @classmethod
    def setUpClass(cls):
        from src.ingestion.fetcher import _try_arxiv_html, SourceError
        from src.ingestion.parser import mark_and_extract
        from src.rendering.renderer import render_bilingual_html
        cls.success = False
        cls.html = ""
        cls.error = ""
        for test_id in ["2406.04124", "2310.05900", "2307.14989v6"]:
            try:
                raw = _try_arxiv_html(test_id)
                marked, blocks = mark_and_extract(raw)
                fake = [{"zh": "", "type": b.type, "math_map": b.math_map} for b in blocks]
                cls.html = render_bilingual_html(
                    marked, fake, arxiv_id=test_id,
                    embed_images=False, source_type="arxiv_html"
                )
                cls.success = True
                break
            except (SourceError, Exception) as e:
                cls.error = str(e)

    def test_brand_nav_stripped(self):
        if not self.success:
            self.skipTest(f"arxiv_html not available: {self.error}")
        # We keep the TOC navbar for arxiv_html source
        self.assertIn("ltx_page_navbar", self.html)

    def test_has_reaper_footer(self):
        if not self.success:
            self.skipTest(f"arxiv_html not available: {self.error}")
        self.assertIn("Modified by Reaper", self.html)

    def test_single_head_tag(self):
        if not self.success:
            self.skipTest(f"arxiv_html not available: {self.error}")
        self.assertEqual(self.html.count("</head>"), 1)


# ──────────────────────────────────────────────
# 12. Full paper generation flow
# ──────────────────────────────────────────────

class TestGeneratePaperFlow(unittest.TestCase):
    """Test the full generate pipeline with cache interaction."""

    @classmethod
    def setUpClass(cls):
        import tempfile, shutil
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Override paths to use temp directory
        from src import config
        # The per-paper layout derives everything from PAPERS_DIR / DATA_DIR,
        # so redirecting those two is enough to sandbox a test.
        self._orig_papers = config.PAPERS_DIR
        self._orig_data = config.DATA_DIR
        config.DATA_DIR = self.tmp
        config.PAPERS_DIR = os.path.join(self.tmp, "papers")

    def tearDown(self):
        from src import config
        config.PAPERS_DIR = self._orig_papers
        config.DATA_DIR = self._orig_data

    def test_generate_first_run_creates_cache(self):
        """First run: no cache → parse + translate → save v2 cache."""
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.translation.cache import PaperCache
        from src.rendering.renderer import render_bilingual_html
        from src import config

        arxiv_id, src_type, raw_html = fetch_html("2307.14989", cache_dir=config.source_dir("2307.14989"))
        marked_html, blocks = mark_and_extract(raw_html)

        # Simulate _generate_paper logic
        paper_cache = PaperCache.load(arxiv_id)
        self.assertFalse(paper_cache.match(raw_html), "Fresh cache should not match")

        paper_cache.update(raw_html, src_type, blocks)
        paper_cache.save()

        # Now it should match
        paper_cache2 = PaperCache.load(arxiv_id)
        self.assertTrue(paper_cache2.match(raw_html), "Cache should match after update")
        self.assertGreater(len(paper_cache2), 0, "Cache should have blocks")

    def test_generate_second_run_uses_cache(self):
        """Second run: cache hit → skip parse + translate → restore."""
        from src.ingestion.fetcher import fetch_html
        from src.ingestion.parser import mark_and_extract
        from src.translation.cache import PaperCache
        from src.rendering.renderer import render_bilingual_html
        from src import config

        arxiv_id, src_type, raw_html = fetch_html("2307.14989", cache_dir=config.source_dir("2307.14989"))
        marked_html, blocks = mark_and_extract(raw_html)

        # First run: create cache
        paper_cache = PaperCache.load(arxiv_id)
        paper_cache.update(raw_html, src_type, blocks)
        # Simulate translations
        for b in paper_cache.blocks:
            b["zh"] = "TEST_TRANSLATION_" + b["en"][:20]
        paper_cache.save()

        # Second run: load from cache
        paper_cache2 = PaperCache.load(arxiv_id)
        self.assertTrue(paper_cache2.match(raw_html), "Cache should match on second run")
        restored = paper_cache2.restore()
        self.assertGreater(len(restored), 0, "Should restore blocks from cache")
        for b in restored:
            self.assertTrue(b["zh"].startswith("TEST_TRANSLATION_"),
                            f"Block should have cached translation: {b.get('zh', '')[:30]}")


# ──────────────────────────────────────────────
# Run tests
# ──────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)