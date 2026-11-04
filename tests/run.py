"""Offline rebuild from the committed canonical corpus; never collects web data.

python run.py
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(__doc__)
    args = parser.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
    steps = [
        # 单元测试先行：链路重建前先保证基础语义未被破坏（P15）
        ("__unittest__", []),
        ("task2/src/build_dictionary.py", []),
        ("task2/src/extract_entities.py", ["--iteration", "baseline"]),
        ("task2/src/extract_entities.py", ["--iteration", "refined"]),
        ("task2/src/visualize.py", ["--iteration", "baseline"]),
        ("task2/src/visualize.py", ["--iteration", "refined"]),
        ("task2/src/spot_check.py", ["--reconcile"]),
        ("task2/src/iter_compare.py", []),
        ("task3/src/parse_routes.py", []),
        ("task3/src/compare_routes.py", []),
        ("task3/src/build_hierarchy_view.py", []),
        ("task4/src/attribute_sentences.py", ["--output", "task4/output/attribution/attributed_sentences.jsonl"]),
        ("task4/src/detect_and_resolve.py", []),
        ("task4/src/annotate_sample.py", ["--score"]),
        # 消解示例依赖当前 pronoun_cases + gold，必须排在 detect_and_resolve 之后（P15）
        ("task4/src/build_resolved_examples.py", []),
        ("task5/src/extract_conditionals.py", []),
        ("task5/src/review_and_charts.py", ["--score"]),
        ("task5/src/review_and_charts.py", ["--charts"]),
        ("task5/src/export_mapping_xlsx.py", []),
        ("task6/src/build_graph.py", []),
        ("task6/src/verify_graph.py", []),
        ("task6/src/visualize_graph.py", []),
        # 默认复现显式选择离线规则模式（提示词 §2.3）；在线模式单独运行、单独记录
        ("task7/src/run_tests.py", ["--rules"]),
    ]
    for script, arguments in steps:
        if script == "__unittest__":
            print("Running unit tests (unittest discover)", flush=True)
            subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover",
                            "-s", "tests", "-t", "."], cwd=ROOT, env=env, check=True)
            continue
        print(f"Running {script}", flush=True)
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / script), *arguments],
                       cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
