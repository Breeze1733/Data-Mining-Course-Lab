"""任意景区/任意篇数/任意来源集合的泛化测试。"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from config import load_config
from extract_entities import extract
from io_utils import load_source_records, merged_specs, safe_filename, sha256_text
from qc_entities import build_gold, silver_poi
from stats_entities import build_induction, run as stats_run

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def entity(**overrides) -> dict:
    base = {
        "type": "景点POI",
        "subtype": "山峰",
        "surface": "飞云峰",
        "normalized": "飞云峰",
        "frequency_key": "飞云峰",
        "scenic_area": "测试峰",
        "source_kind": "blog",
        "source_record_id": "B1",
        "start": 0,
        "end": 3,
        "is_root_area": False,
        "counts_as_time_node": True,
        "confidence": 0.5,
    }
    base.update(overrides)
    return base


class GeneralizationTests(unittest.TestCase):
    def test_missing_optional_source_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = "飞云峰很美。"
            write_jsonl(
                root / "tourist_routes_clean.jsonl",
                [
                    {
                        "record_id": "T1",
                        "scenic_area": "测试峰",
                        "cleaned_text": text,
                        "text_sha256": sha256_text(text),
                    }
                ],
            )
            config = load_config()
            records, summaries = load_source_records(
                root,
                ["tourist", "official_document"],
                specs=merged_specs(config["input"]["sources"]),
                field_map=config["input"]["field_map"],
            )
            self.assertEqual(len(records), 1)
            statuses = {item["source_kind"]: item["status"] for item in summaries}
            self.assertEqual(statuses["tourist"], "ok")
            self.assertEqual(statuses["official_document"], "missing_optional")

            payload = extract(
                input_dir=root,
                resources_dir=RESOURCES,
                output_dir=root / "out",
                iteration="test",
                sources=["tourist", "official_document"],
                generated_at="2026-10-28T00:00:00+08:00",
                use_jieba=False,
                stopwords_path=RESOURCES / "stopwords_extraction.txt",
                verify_manifest=False,
                config=config,
            )
            self.assertEqual(payload["counts"]["documents"], 1)
            self.assertTrue(
                any(
                    item["code"] == "missing_optional_source"
                    for item in payload["counts"]["warnings"]
                )
            )

    def test_safe_filename(self) -> None:
        self.assertEqual(safe_filename("A/B:C"), "A_B_C")
        self.assertTrue(safe_filename("").startswith("area_"))
        self.assertEqual(safe_filename("黄山"), "黄山")

    def test_stats_supports_unknown_source_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = {
                "entities": [
                    entity(),
                    entity(type="交通方式", subtype="索道缆车", surface="索道", normalized="索道", frequency_key="索道"),
                    entity(
                        type="时间节点",
                        subtype="时刻",
                        surface="15:30",
                        normalized="15:30",
                        frequency_key="15:30",
                    ),
                ],
                "warnings": [],
            }
            entities_path = root / "entities.json"
            entities_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            output = root / "stats"
            summary = stats_run(entities_path, output, scope="blog", config=load_config())
            self.assertEqual(summary["source_kinds"], ["blog"])
            with (output / "frequency_detail.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle))
            self.assertIn("blog_count", header)
            induction = (output / "type_system_induction.md").read_text(encoding="utf-8")
            self.assertIn("只有一个景区", induction)
            self.assertNotIn("黄山", induction)

    def test_induction_handles_one_area_and_many_areas(self) -> None:
        one = build_induction([entity()], load_config())
        self.assertIn("只有一个景区", one)
        many = build_induction(
            [entity(), entity(scenic_area="另一峰", frequency_key="碧波湖", surface="碧波湖")],
            load_config(),
        )
        self.assertNotIn("只有一个景区", many)

    def test_missing_silver_standard_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_jsonl(
                root / "tourist_routes_clean.jsonl",
                [{"record_id": "T1", "scenic_area": "测试峰", "cleaned_text": "飞云峰很美。"}],
            )
            gold = build_gold(root, load_config())
            self.assertEqual(gold, {"T1": []})
            silver = silver_poi([], gold)
            self.assertFalse(silver["available"])


if __name__ == "__main__":
    unittest.main()
