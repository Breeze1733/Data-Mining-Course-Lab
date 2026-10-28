"""端到端抽取管线测试（合成数据、离线）。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from extract_entities import extract, main
from io_utils import sha256_text

RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def write_tourist(path: Path) -> None:
    records = [
        {
            "record_id": "TEST001",
            "scenic_area": "黄山",
            "source_platform": "携程",
            "source_url": "https://example.com/1",
            "title": "黄山两日",
            "cleaned_text": "早上8点从云谷寺坐云谷索道到玉屏楼，下午3点半下山。",
            "matched_pois": ["云谷", "玉屏"],
            "text_sha256": "",
        },
        {
            "record_id": "TEST002",
            "scenic_area": "九寨沟",
            "source_platform": "小红书",
            "source_url": "https://example.com/2",
            "title": "九寨沟一日",
            "cleaned_text": "坐观光车到诺日朗中心站，2小时后到长海。",
            "matched_pois": ["诺日朗", "长海"],
            "text_sha256": "",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            record["text_sha256"] = sha256_text(record["cleaned_text"])
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class PipelineTests(unittest.TestCase):
    def test_extract_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_tourist(root / "tourist_routes_clean.jsonl")
            output = root / "out"
            payload = extract(
                input_dir=root,
                resources_dir=RESOURCES,
                output_dir=output,
                iteration="test",
                sources=["tourist"],
                areas=None,
                limit=None,
                record_id=None,
                generated_at="2026-10-28T00:00:00+08:00",
                use_jieba=False,
                stopwords_path=RESOURCES / "stopwords_extraction.txt",
                verify_manifest=False,
            )
            self.assertEqual(payload["counts"]["documents"], 2)
            self.assertGreater(payload["counts"]["entities"], 0)
            self.assertTrue((output / "entities.json").exists())
            self.assertTrue((output / "entities.jsonl").exists())

            data = json.loads((output / "entities.json").read_text(encoding="utf-8"))
            for entity in data["entities"]:
                record_text = {
                    "TEST001": "早上8点从云谷寺坐云谷索道到玉屏楼，下午3点半下山。",
                    "TEST002": "坐观光车到诺日朗中心站，2小时后到长海。",
                }[entity["source_record_id"]]
                self.assertEqual(
                    record_text[entity["start"] : entity["end"]], entity["surface"]
                )
            self.assertTrue(
                any(
                    entity["surface"] == "云谷索道" and entity["type"] == "交通方式"
                    for entity in data["entities"]
                )
            )
            self.assertTrue(
                any(
                    entity["subtype"] == "时刻" and entity["normalized"] == "15:30"
                    for entity in data["entities"]
                )
            )
            self.assertTrue(
                any(
                    entity["subtype"] == "时长"
                    and entity["counts_as_time_node"] is False
                    for entity in data["entities"]
                )
            )

    def test_missing_input_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(
                    [
                        "--input-dir",
                        str(root),
                        "--resources",
                        str(RESOURCES),
                        "--output-dir",
                        str(root / "out"),
                        "--sources",
                        "tourist",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("缺少 task1 预处理输出", stderr.getvalue())

    def test_idempotent_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_tourist(root / "tourist_routes_clean.jsonl")
            outputs = []
            for name in ("a", "b"):
                output = root / name
                extract(
                    input_dir=root,
                    resources_dir=RESOURCES,
                    output_dir=output,
                    iteration="test",
                    sources=["tourist"],
                    areas=None,
                    limit=None,
                    record_id=None,
                    generated_at="2026-10-28T00:00:00+08:00",
                    use_jieba=False,
                    stopwords_path=RESOURCES / "stopwords_extraction.txt",
                    verify_manifest=False,
                )
                outputs.append((output / "entities.json").read_bytes())
            self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
