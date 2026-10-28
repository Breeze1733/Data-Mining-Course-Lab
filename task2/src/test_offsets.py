"""偏移与切分单元测试（离线）。"""

from __future__ import annotations

import unittest

from offsets import (
    assert_span,
    build_length_preserving_view,
    build_sentence_spans,
    context_window,
    locate,
    trim_span,
)


class OffsetTests(unittest.TestCase):
    def test_trim_and_assert(self) -> None:
        text = "（光明顶），然后下山"
        start, end = trim_span(text, 0, 6)
        self.assertEqual(text[start:end], "光明顶")
        assert_span(text, start, end, "光明顶")

    def test_offset_mismatch_raises(self) -> None:
        text = "光明顶"
        with self.assertRaises(AssertionError):
            assert_span(text, 0, 2, "光明顶")

    def test_sentence_and_clause(self) -> None:
        text = "早上8点出发。先到云谷寺，再坐索道上山！"
        sentences = build_sentence_spans(text)
        self.assertEqual(len(sentences), 2)
        start = text.index("云谷寺")
        sentence_index, clause_index, s_start, s_end, _, _ = locate(text, start, start + 3)
        self.assertEqual(sentence_index, 1)
        self.assertGreaterEqual(clause_index, 0)
        self.assertEqual(text[s_start:s_end], "先到云谷寺，再坐索道上山！")

    def test_context_window(self) -> None:
        text = "0123456789光明顶abcdefghij"
        start = text.index("光明顶")
        context, c_start, c_end = context_window(text, start, start + 3, radius=3)
        self.assertEqual(context, "789光明顶abc")
        self.assertEqual(c_start, start - 3)
        self.assertEqual(c_end, start + 3 + 3)

    def test_length_preserving_view(self) -> None:
        text = "１７：３５"
        view, index_map = build_length_preserving_view(text)
        self.assertEqual(view, "17:35")
        self.assertEqual(len(view), len(text))
        self.assertEqual(index_map, list(range(len(text))))


if __name__ == "__main__":
    unittest.main()
