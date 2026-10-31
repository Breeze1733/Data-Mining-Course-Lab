"""Offline rebuild from the committed canonical corpus; never collects web data.

python run.py
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(__doc__)
    args = parser.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
    steps = [
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
        ("task4/src/detect_and_resolve.py", []),
        ("task4/src/annotate_sample.py", ["--score"]),
        ("task5/src/extract_conditionals.py", []),
        ("task5/src/review_and_charts.py", ["--score"]),
        ("task5/src/review_and_charts.py", ["--charts"]),
        ("task5/src/export_mapping_xlsx.py", []),
        ("task6/src/build_graph.py", []),
        ("task6/src/verify_graph.py", []),
        ("task6/src/visualize_graph.py", []),
        ("task7/src/run_tests.py", []),
    ]
    for script, arguments in steps:
        print(f"Running {script}", flush=True)
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / script), *arguments],
                       cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
