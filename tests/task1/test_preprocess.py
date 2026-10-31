"""Regression tests for semantic preservation, validation and lossless exports.

Run from task1: python -m unittest discover -s src -p test_preprocess.py -v
The strings below are artificial unit-test fixtures, not collected source data.
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "task1/src"))
from preprocess import canonicalize_url, clean_text, export_outputs, preprocess_records


def fixture(**changes):
    row = {
        "record_id": "unit_001", "scenic_area": "黄山", "source_platform": "unit_test_fixture",
        "source_url": "https://example.org/article/1", "title": "黄山路线测试",
        "text_type": "official_route", "collected_at": "2026-10-28T12:00:00+08:00",
        "raw_content": "测试路线：上午8:30到达云谷寺→始信峰→光明顶，下午16:00下山。保留各站顺序及数值。",
        "raw_format": "text", "extraction_selector": "fixture", "raw_file": "fixture_only",
        "content_scope": "artificial unit test fixture; never collected data", "author": "", "published_at": "",
    }
    row.update(changes)
    return row


class CleaningTests(unittest.TestCase):
    def test_html_noise_removed_without_losing_route_or_time(self):
        raw = '<nav>首页 导航</nav><article><p>黄山　路线：８：３０ 云谷寺→始信峰➡光明顶</p><p>海拔１８６０米&nbsp;下午１６：００下山。</p><script>steal()</script><p style="display:none">隐藏广告</p></article>'
        text, counts, _ = clean_text(raw, "html")
        self.assertIn("8:30 云谷寺→始信峰➡光明顶", text)
        self.assertIn("1860米 下午16:00下山", text)
        self.assertNotIn("导航", text)
        self.assertNotIn("steal", text)
        self.assertNotIn("隐藏广告", text)
        self.assertGreaterEqual(counts["html_noncontent_blocks_removed"], 3)

    def test_emoji_url_control_and_long_duplicates(self):
        long_line = "黄山路线经过始信峰和光明顶，游客需要根据自己的体力安排停留时间，下午沿原路返回云谷寺。"
        raw = "收藏 99\n\u200b🧭黄山：08:10→09:20\nhttps://example.org/noise\n" + long_line + "\n" + long_line + "\n光明顶\n光明顶"
        text, counts, _ = clean_text(raw)
        self.assertNotIn("example.org", text)
        self.assertNotIn("\u200b", text)
        self.assertNotIn("🧭", text)
        self.assertNotIn("收藏", text)
        self.assertIn("08:10→09:20", text)
        self.assertEqual(text.count(long_line.replace("，", ",")), 1)
        self.assertTrue(text.endswith("光明顶\n光明顶"))
        self.assertEqual(counts["duplicate_long_paragraphs_removed"], 1)

    def test_reject_empty_and_tracking_url_duplicate(self):
        rows, report, rejected, _ = preprocess_records([
            fixture(), fixture(record_id="unit_002", raw_content="<script>empty()</script>", raw_format="html"),
            fixture(record_id="unit_003", source_url="https://example.org/article/1?utm_source=test#comments", raw_content="另外一条黄山路线从玉屏楼出发，上午经过迎客松后，继续游览天都峰周边，下午乘坐索道返回山下。"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(any("empty_clean_content" in item["rejection_reasons"] for item in rejected))
        self.assertTrue(any(any(x.startswith("duplicate_source_url:") for x in item["rejection_reasons"]) for item in rejected))
        self.assertEqual(report["duplicate_source_urls_in_accepted"], 0)

    def test_bad_url_and_missing_field_are_not_accepted(self):
        rows, report, rejected, _ = preprocess_records([fixture(source_url="javascript:alert(1)", title="")])
        self.assertFalse(rows)
        self.assertIn("invalid_source_url", rejected[0]["rejection_reasons"])
        self.assertEqual(report["missing_required_fields_in_input"]["title"], 1)

    def test_mojibake_is_flagged_not_replaced_by_guessed_words(self):
        rows, report, _, _ = preprocess_records([fixture(raw_content=fixture()["raw_content"] + "原页面含有�与锟斤拷字符。")])
        self.assertIn("�", rows[0]["clean_content"])
        self.assertIn("锟斤拷", rows[0]["clean_content"])
        self.assertIn("replacement_character_present", rows[0]["quality_flags"])
        self.assertIn("suspected_encoding_corruption", rows[0]["quality_flags"])

    def test_url_identity_parameters_preserved(self):
        self.assertEqual(canonicalize_url("https://EXAMPLE.org/read?id=123&utm_source=x#abc"), "https://example.org/read?id=123")
        self.assertNotEqual(canonicalize_url("https://example.org/read?id=123"), canonicalize_url("https://example.org/read?id=124"))

    def test_unicode_numbers_units_and_route_semantics_survive(self):
        raw = "①路线Ⅰ：２²km，水温２０℃，水质H₂O。②路线Ⅱ：Ａ➕Ｂ➖Ｃ。✅可走 ✔推荐 ❌不走 ✘关闭 ⚠危险 🚫禁止入内 ❤装饰"
        text, counts, _ = clean_text(raw)
        self.assertIn("①路线Ⅰ:2²km", text)
        self.assertNotIn("22km", text)
        self.assertIn("20℃", text)
        self.assertIn("H₂O", text)
        self.assertIn("②路线Ⅱ:A➕B➖C", text)
        for semantic in ("✅可走", "✔推荐", "❌不走", "✘关闭", "⚠危险", "🚫禁止入内"):
            self.assertIn(semantic, text)
        self.assertNotIn("❤", text)
        self.assertGreater(counts["fullwidth_characters_normalized"], 0)

    def test_deduplication_does_not_conflate_opposite_semantic_symbols(self):
        common = "黄山上午从云谷寺出发，经过始信峰到达光明顶，下午根据体力选择后续游览路线。"
        rows, _, rejected, _ = preprocess_records([
            fixture(raw_content=common + "✔路段A➕路段B"),
            fixture(record_id="unit_002", source_url="https://example.org/article/2", raw_content=common + "✘路段A➖路段B"),
        ])
        self.assertEqual(len(rows), 2)
        self.assertFalse(rejected)

    def test_long_excel_cell_is_externalized_without_csv_json_loss(self):
        huge = fixture()["raw_content"] + "\n" + ("很长的黄山游览叙述。" * 4000)
        rows, report, rejected, examples = preprocess_records([fixture(raw_content=huge)])
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            export_outputs(out, rows, report, rejected, examples)
            written = json.loads((out / "dataset_clean.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(written["raw_content"], huge)
            with (out / "dataset_clean.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(next(csv.DictReader(handle))["raw_content"], huge)
            audit = json.loads((out / "quality_report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(audit["xlsx_long_text_externalization"]), 2)
            for entry in audit["xlsx_long_text_externalization"]:
                self.assertEqual((out / entry["path"]).read_text(encoding="utf-8"), rows[0][entry["field"]])
                self.assertEqual((out / entry["path"]).read_bytes(), rows[0][entry["field"]].encode("utf-8"))
            self.assertFalse((out / "dataset_clean.xlsx").exists())
            self.assertEqual(audit["xlsx_authoring"]["engine"], "@oai/artifact-tool")


if __name__ == "__main__":
    unittest.main()
