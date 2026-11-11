"""Rebuild experiments 2–6 and verify the frozen submission evidence offline."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_steps() -> list:
    steps = [
        # unit tests first: verify basic semantics are intact before rebuilding the pipeline
        ("__unittest__", []),
        # Export the dictionary from the submitted resources.
        ("task2/src/export_dictionary.py", []),
        ("task2/src/extract_entities.py", ["--iteration", "baseline"]),
        ("task2/src/extract_entities.py", ["--iteration", "refined"]),
        ("task2/src/visualize.py", ["--iteration", "baseline"]),
        ("task2/src/visualize.py", ["--iteration", "refined"]),
        ("task2/src/spot_check.py", ["--reconcile"]),
        # sentence-level entity evaluation (recall measurable for the first time; artifact entity_sentence_eval.json)
        ("task2/src/entity_sentence_eval.py", []),
        ("task2/src/compare_iterations.py", []),
        ("task3/src/parse_routes.py", []),
        ("task3/src/compare_routes.py", []),
        ("task3/src/build_hierarchy_view.py", []),
        ("task4/src/attribute_sentences.py", ["--output", "task4/output/attribution/attributed_sentences.jsonl"]),
        ("task4/src/detect_and_resolve.py", []),
        ("task4/src/annotate_sample.py", ["--score"]),
        # resolution examples depend on the current pronoun_cases + gold; must run after detect_and_resolve
        ("task4/src/build_resolved_examples.py", []),
        ("task5/src/extract_conditionals.py", []),
        ("task5/src/review_and_charts.py", ["--score"]),
        ("task5/src/review_and_charts.py", ["--charts"]),
        ("task5/src/review_and_charts.py", ["--xlsx"]),
        # original-sentence-level coverage evaluation (missed/over-extracted entities measurable for the first time)
        ("task5/src/coverage_eval.py", []),
        ("task6/src/build_graph.py", []),
        ("task6/src/verify_graph.py", []),
        ("task6/src/visualize_graph.py", []),
        # cross-task data contract check (boundary field consistency, read-only; any violation fails the chain)
        ("common/contract_check.py", []),
    ]
    return steps


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
    steps = build_steps()
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
