"""预处理阶段的单元测试。

从 task1 目录运行：
    python -m unittest discover -s src -p test_preprocess_collected.py -v

测试串均为人工构造的夹具，不是采集到的真实数据。
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from preprocess_collected import (
    clean_text,
    deduplicate,
    detect_near_duplicates,
    normalize_width,
    official_route_row,
    tourist_row,
    write_csv,
)


def tourist_fixture(**changes):
    row = {
        "record_id": "unit_tourist_001",
        "scenic_area": "黄山",
        "source_platform": "携程",
        "text_type": "游记",
        "source_url": "https://example.org/travel/1",
        "title": "黄山路线测试",
        "author": "测试作者",
        "published_at": "2026-10-01",
        "collected_at": "2026-10-28T12:00:00+08:00",
        "body_text": "上午8:30从云谷寺上山→始信峰→光明顶，下午16:00下山。",
        "raw_format": "text",
    }
    row.update(changes)
    return row


class CleaningTests(unittest.TestCase):
    def test_html_noise_removed_but_route_preserved(self):
        raw = (
            "<nav>首页 导航</nav><article><p>黄山　路线：８：３０ 云谷寺→始信峰➡光明顶</p>"
            "<p>海拔１８６０米&nbsp;下午１６：００下山。</p>"
            "<script>steal()</script><p style='display:none'>隐藏广告</p></article>"
        )
        cleaned, tags, counts = clean_text(raw, "html")
        self.assertIn("8：30 云谷寺→始信峰➡光明顶", cleaned)
        self.assertIn("1860米 下午16：00下山", cleaned)
        self.assertNotIn("导航", cleaned)
        self.assertNotIn("steal", cleaned)
        self.assertNotIn("隐藏广告", cleaned)
        self.assertGreaterEqual(counts["html_noncontent_blocks_removed"], 2)
        self.assertEqual(tags, [])

    def test_hashtags_mentions_emoji_and_arrows(self):
        raw = (
            "大家好@旅行者\n"
            "✅ 北宫门➡️佛香阁➡️十七孔桥\n"
            "😭😭 太美了❗\n"
            "#颐和园 #北京旅游 #颐和园"
        )
        cleaned, tags, counts = clean_text(raw, "text")
        self.assertEqual(tags, ["颐和园", "北京旅游"])
        self.assertIn("北宫门➡佛香阁➡十七孔桥", cleaned)
        self.assertIn("✅", cleaned)
        self.assertIn("❗", cleaned)
        self.assertNotIn("😭", cleaned)
        self.assertNotIn("@旅行者", cleaned)
        self.assertNotIn("#颐和园", cleaned)
        self.assertEqual(counts["hashtags_moved_to_tags"], 3)

    def test_metadata_lines_and_duplicate_long_lines(self):
        long_line = "从云谷寺上山经过始信峰和光明顶，下午沿原路返回云谷寺，全程约六小时，途中注意脚下湿滑并预留休息时间。"
        raw = "\n".join([
            "分享 12",
            "展开全文",
            long_line,
            long_line,
            "责任编辑：张三",
            "正文保留：光明顶→飞来石。",
        ])
        cleaned, _, counts = clean_text(raw, "text")
        self.assertEqual(cleaned.count(long_line), 1)
        self.assertIn("正文保留：光明顶→飞来石。", cleaned)
        self.assertNotIn("展开全文", cleaned)
        self.assertNotIn("责任编辑", cleaned)
        self.assertEqual(counts["metadata_lines_removed"], 3)
        self.assertEqual(counts["duplicate_long_lines_removed"], 1)

    def test_width_and_space_normalization_keeps_chinese_punctuation(self):
        raw = "时间１２：３０，门票６０元（含佛香阁）。　下一段\xa0继续。"
        cleaned, _, counts = clean_text(raw, "text")
        self.assertIn("12：30，门票60元（含佛香阁）", cleaned)
        self.assertIn("下一段 继续。", cleaned)
        self.assertNotIn("　", cleaned)
        self.assertNotIn("\xa0", cleaned)
        self.assertGreaterEqual(counts["fullwidth_characters_normalized"], 6)

    def test_normalize_width_does_not_fold_semantic_notation(self):
        text, changed = normalize_width("① 2²km ２５℃ ＡＢＣ")
        self.assertIn("①", text)
        self.assertIn("2²km", text)
        self.assertIn("25℃", text)
        self.assertIn("ABC", text)
        self.assertEqual(changed, 5)

    def test_cleaning_is_idempotent(self):
        raw = "<p>第一天：云谷寺→始信峰</p>\n\n<p>#黄山 #攻略</p>"
        once, _, _ = clean_text(raw, "html")
        twice, _, _ = clean_text(once, "text")
        self.assertEqual(once, twice)


class QualityTests(unittest.TestCase):
    def test_short_text_flagged(self):
        row, errors, _ = tourist_row(tourist_fixture(body_text="太短"), min_chars=80)
        self.assertEqual(errors, [])
        self.assertIn("too_short", row["quality_flags"])

    def test_missing_required_field_rejected(self):
        row, errors, _ = tourist_row(tourist_fixture(source_url=""), min_chars=80)
        self.assertIsNone(row)
        self.assertTrue(any("missing_required_fields" in error for error in errors))

    def test_missing_optional_metadata_flagged_not_rejected(self):
        row, errors, _ = tourist_row(
            tourist_fixture(author="", published_at=""), min_chars=80
        )
        self.assertEqual(errors, [])
        self.assertIn("missing_author", row["quality_flags"])
        self.assertIn("missing_publication_date", row["quality_flags"])

    def test_residual_noise_flags(self):
        row, _, _ = tourist_row(
            tourist_fixture(body_text="路线见 <b>云谷寺</b>，上午上山，下午下山，全程六小时。"),
            min_chars=10,
        )
        self.assertIn("residual_html", row["quality_flags"])


class DeduplicationTests(unittest.TestCase):
    def test_tourist_duplicate_by_text_fingerprint(self):
        rows = [
            {"record_id": "A", "source_url": "https://a", "text_sha256": "same"},
            {"record_id": "B", "source_url": "https://b", "text_sha256": "same"},
        ]
        kept, removed = deduplicate(rows, "tourist")
        self.assertEqual([row["record_id"] for row in kept], ["A"])
        self.assertIn("duplicate_text_sha256:A", removed[0]["reason"])

    def test_official_routes_sharing_document_url_are_both_kept(self):
        rows = [
            {"route_id": "R1", "source_url": "https://same/doc", "text_sha256": "x"},
            {"route_id": "R2", "source_url": "https://same/doc", "text_sha256": "y"},
        ]
        kept, removed = deduplicate(rows, "route")
        self.assertEqual(len(kept), 2)
        self.assertEqual(removed, [])

    def test_near_duplicate_marked_not_removed(self):
        base = (
            "从北宫门进入后先到四大部洲，沿石阶向上到达佛香阁，殿前平台能够俯瞰昆明湖全景，"
            "随后沿长廊向东步行，廊间彩画密集，途中在排云门附近休息补水并整理随身物品，"
            "继续前往十七孔桥，桥上石狮形态各异，傍晚柔光适合拍照，桥头人流较少，"
            "过桥到南湖岛环岛一周，再从东宫门离园，全程约四小时且以平缓道路为主。"
        )
        rows = [
            {"record_id": "A", "scenic_area": "颐和园", "source_platform": "小红书",
             "cleaned_text": base, "quality_flags": []},
            {"record_id": "B", "scenic_area": "颐和园", "source_platform": "小红书",
             "cleaned_text": base.replace("全景", "全貌", 1), "quality_flags": []},
        ]
        findings = detect_near_duplicates(rows, threshold=0.90)
        self.assertEqual(len(findings), 1)
        self.assertIn("near_duplicate_of:A", rows[1]["quality_flags"])
        self.assertEqual(len(rows), 2)


class ExportTests(unittest.TestCase):
    def test_csv_escapes_formula_like_cells_and_keeps_chinese(self):
        rows = [{"id": "1", "title": "=SUM(A1)", "body": "第一段，第二段。"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            write_csv(path, rows, ["id", "title", "body"])
            with path.open(encoding="utf-8-sig", newline="") as fh:
                exported = list(csv.DictReader(fh))
        self.assertEqual(exported[0]["title"], "'=SUM(A1)")
        self.assertEqual(exported[0]["body"], "第一段，第二段。")

    def test_official_route_row_keeps_order_flag(self):
        row, errors, _ = official_route_row(
            {
                "route_id": "R1",
                "source_record_id": "DOC1",
                "scenic_area": "九寨沟",
                "source_url": "https://example.org/route",
                "title": "一日游",
                "raw_content": "沟口乘车→原始森林→芳草海→诺日朗中心站。",
                "ordered_route": True,
            },
            min_chars=10,
        )
        self.assertEqual(errors, [])
        self.assertTrue(row["ordered_route"])
        self.assertEqual(row["quality_flags"], [])


if __name__ == "__main__":
    unittest.main()
