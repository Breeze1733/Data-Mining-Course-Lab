"""运行清单的目录扫描测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_manifest import run
from config import load_config


class ManifestTests(unittest.TestCase):
    def test_discovers_nested_outputs_and_extra_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root / "inputs"
            outputs = root / "outputs"
            (inputs / "nested").mkdir(parents=True)
            (outputs / "by_area").mkdir(parents=True)
            (outputs / "charts").mkdir(parents=True)
            (inputs / "tourist_routes_clean.jsonl").write_text("{}\n", encoding="utf-8")
            (inputs / "extra_notes.json").write_text("{}", encoding="utf-8")
            (inputs / "manifest.json").write_text('{"files": []}', encoding="utf-8")
            (outputs / "entities.json").write_text("{}", encoding="utf-8")
            (outputs / "by_area" / "测试峰.json").write_text("{}", encoding="utf-8")
            (outputs / "charts" / "poi_top20.png").write_bytes(b"png")
            (outputs / "charts" / "stale.tmp").write_text("tmp", encoding="utf-8")
            manifest_path = outputs / "run_manifest.json"

            manifest = run(
                outputs,
                inputs,
                manifest_path,
                config=load_config(),
                config_path=None,
            )
            output_paths = {item["path"] for item in manifest["outputs"]}
            self.assertIn("entities.json", output_paths)
            self.assertIn("by_area/测试峰.json", output_paths)
            self.assertIn("charts/poi_top20.png", output_paths)
            self.assertNotIn("run_manifest.json", output_paths)
            self.assertNotIn("charts/stale.tmp", output_paths)
            input_paths = {item["path"] for item in manifest["inputs"]}
            self.assertIn("tourist_routes_clean.jsonl", input_paths)
            self.assertIn("extra_notes.json", input_paths)
            self.assertNotIn("manifest.json", input_paths)
            self.assertTrue(manifest_path.exists())
            json.loads(manifest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
