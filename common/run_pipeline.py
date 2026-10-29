"""Offline rebuild from the committed canonical corpus; never collects web data.

python common/run_pipeline.py --reports --document-python <python executable>
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--reports", action="store_true")
    parser.add_argument("--document-python", default=sys.executable)
    args = parser.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    steps = [
        ("task2/src/build_dictionary.py", []),
        ("task2/src/extract_entities.py", ["--iteration", "baseline"]),
        ("task2/src/extract_entities.py", ["--iteration", "refined"]),
        ("task2/src/visualize.py", ["--iteration", "baseline"]),
        ("task2/src/visualize.py", ["--iteration", "refined"]),
        ("common/reconcile_entity_reviews.py", []),
        ("task2/src/iter_compare.py", []),
        ("task3/src/parse_routes.py", []),
        ("task3/src/compare_routes.py", []),
        ("task3/src/build_hierarchy_view.py", []),
        ("task4/src/detect_and_resolve.py", []),
        ("task4/src/annotate_sample.py", ["--score"]),
        ("task6/src/build_graph.py", []),
        ("task6/src/verify_graph.py", []),
        ("common/verify_entity_identity.py", []),
        ("task6/src/visualize_graph.py", []),
        ("task7/src/run_tests.py", []),
    ]
    for script, arguments in steps:
        print(f"Running {script}", flush=True)
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / script), *arguments],
                       cwd=ROOT, env=env, check=True)
    if args.reports:
        for task in (1, 2, 3, 4, 6, 7):
            subprocess.run([args.document_python, "-X", "utf8", str(ROOT / f"task{task}/src/build_report{task}.py")],
                           cwd=ROOT, env=env, check=True)
        subprocess.run([args.document_python, "-X", "utf8", str(ROOT / "common/build_summary_doc.py")],
                       cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
