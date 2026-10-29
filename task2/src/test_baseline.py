"""iter1 基线来源回退与确定性测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_baseline import run
from config import load_config
from io_utils import sha256_text


def write_tourist(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            row = dict(row)
            row["text_sha256"] = sha256_text(row["cleaned_text"])
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class BaselineTests(unittest.TestCase):
    def test_matched_pois_is_primary_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_tourist(
                root / "tourist_routes_clean.jsonl",
                [
                    {
                        "record_id": "T1",
                        "scenic_area": "测试谷",
                        "cleaned_text": "飞云峰和碧波湖。",
                        "matched_pois": ["飞云峰", "碧波湖"],
                    }
                ],
            )
            metadata = run(load_config(), root, root / "baseline")
            self.assertEqual(metadata["derivation"], "matched_pois")
            self.assertEqual(metadata["nodes"]["测试谷"], 2)
            self.assertTrue((root / "baseline" / "metadata.json").exists())

    def test_generic_fallback_when_no_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_tourist(
                root / "tourist_routes_clean.jsonl",
                [
                    {
                        "record_id": "T1",
                        "scenic_area": "测试谷",
                        "cleaned_text": "飞云峰很美。",
                    },
                    {
                        "record_id": "T2",
                        "scenic_area": "测试谷",
                        "cleaned_text": "再去飞云峰。",
                    },
                ],
            )
            metadata = run(load_config(), root, root / "baseline")
            self.assertEqual(metadata["derivation"], "generic")
            self.assertGreater(metadata["nodes"]["测试谷"], 0)

    def test_baseline_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_tourist(
                root / "tourist_routes_clean.jsonl",
                [
                    {
                        "record_id": "T1",
                        "scenic_area": "测试谷",
                        "cleaned_text": "飞云峰和碧波湖。",
                        "matched_pois": ["飞云峰", "碧波湖"],
                    }
                ],
            )
            first = root / "a"
            second = root / "b"
            run(load_config(), root, first)
            run(load_config(), root, second)
            self.assertEqual(
                (first / "poi_gazetteer.csv").read_bytes(),
                (second / "poi_gazetteer.csv").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
