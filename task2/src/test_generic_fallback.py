"""未知景区通用后缀兜底测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import load_config
from extract_entities import extract
from io_utils import sha256_text

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def write_records(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            row = dict(row)
            row.setdefault("source_platform", "test")
            row.setdefault("source_url", "https://example.com/" + row["record_id"])
            row.setdefault("title", row["record_id"])
            row.setdefault("matched_pois", [])
            row["text_sha256"] = sha256_text(row["cleaned_text"])
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_extract(root: Path, rows: list[dict], **kwargs):
    write_records(root / "tourist_routes_clean.jsonl", rows)
    return extract(
        input_dir=root,
        resources_dir=RESOURCES,
        output_dir=root / "out",
        iteration="test",
        sources=["tourist"],
        generated_at="2026-10-28T00:00:00+08:00",
        use_jieba=False,
        stopwords_path=RESOURCES / "stopwords_extraction.txt",
        verify_manifest=False,
        config=load_config(),
        **kwargs,
    )


class GenericFallbackTests(unittest.TestCase):
    def test_unknown_area_gets_low_confidence_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = run_extract(
                root,
                [
                    {
                        "record_id": "UNK1",
                        "scenic_area": "张家界",
                        "cleaned_text": "从游客中心出发，先到飞云峰，再去碧波湖，坐索道下山。酒店和车站不算。",
                    },
                    {
                        "record_id": "UNK2",
                        "scenic_area": "飞霞",
                        "cleaned_text": "飞霞景区风景不错，飞云峰很美。",
                    },
                ],
            )
            entities = payload["entities"]
            by_surface = {entity["surface"]: entity for entity in entities}
            self.assertIn("飞云峰", by_surface)
            self.assertEqual(by_surface["飞云峰"]["type"], "景点POI")
            self.assertEqual(by_surface["飞云峰"]["method"], "generic_suffix")
            self.assertLessEqual(by_surface["飞云峰"]["confidence"], 0.6)
            self.assertTrue(by_surface["飞云峰"]["fallback"])
            self.assertIn("碧波湖", by_surface)
            self.assertIn("游客中心", by_surface)
            self.assertEqual(by_surface["索道"]["type"], "交通方式")
            self.assertNotIn("酒店", by_surface)
            self.assertNotIn("车站", by_surface)

            root_entities = [entity for entity in entities if entity.get("is_root_area")]
            self.assertTrue(any(entity["surface"] == "飞霞景区" for entity in root_entities))

            warning_codes = {item["code"] for item in payload["counts"]["warnings"]}
            self.assertIn("missing_gazetteer_area", warning_codes)
            fallback = payload["counts"]["poi_fallback"]
            self.assertEqual(fallback["mode"], "missing_area_only")
            self.assertIn("张家界", fallback["areas_without_gazetteer"])
            self.assertGreater(fallback["entities"], 0)

    def test_fallback_disabled_still_warns(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = run_extract(
                root,
                [
                    {
                        "record_id": "UNK1",
                        "scenic_area": "张家界",
                        "cleaned_text": "从游客中心出发，先到飞云峰，再去碧波湖。",
                    }
                ],
                generic_fallback="off",
            )
            poi = [entity for entity in payload["entities"] if entity["type"] == "景点POI"]
            self.assertEqual(poi, [])
            warnings = payload["counts"]["warnings"]
            self.assertTrue(
                any(item["code"] == "missing_gazetteer_area" and item["fallback"] == "disabled" for item in warnings)
            )

    def test_known_area_does_not_use_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = run_extract(
                root,
                [
                    {
                        "record_id": "HS1",
                        "scenic_area": "黄山",
                        "cleaned_text": "光明顶看日出，再去迎客松。",
                    }
                ],
            )
            self.assertFalse(
                any(entity["method"] == "generic_suffix" for entity in payload["entities"])
            )
            self.assertEqual(payload["counts"]["poi_fallback"]["areas_without_gazetteer"], [])


if __name__ == "__main__":
    unittest.main()
