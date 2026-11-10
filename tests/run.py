"""Offline rebuild from the committed canonical corpus; never collects web data.

python run.py [--task7 rules|llm|both]

Task 7 acceptance modes (prompt §2.3):
  rules  Default. Offline rules mode, static reproduction criteria (--rules is passed
         explicitly; never goes online because of a local config.json).
  llm    Online dynamic acceptance: calls the configured LLM to produce itineraries and
         answers; artifacts are written separately to *_llm.json / traces_llm/ and never
         overwrite offline acceptance evidence; requires task7/config.json.
  both   Offline static reproduction first, then online dynamic acceptance.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_steps(task7_mode: str) -> list:
    steps = [
        # unit tests first: verify basic semantics are intact before rebuilding the pipeline
        ("__unittest__", []),
        # miss-driven expansion of the dictionary/time rules (idempotent; must run before build_dictionary)
        ("task2/src/expand_dictionary.py", []),
        ("task2/src/extract_entities.py", ["--iteration", "baseline"]),
        ("task2/src/extract_entities.py", ["--iteration", "refined"]),
        ("task2/src/visualize.py", ["--iteration", "baseline"]),
        ("task2/src/visualize.py", ["--iteration", "refined"]),
        ("task2/src/spot_check.py", ["--reconcile"]),
        # sentence-level entity evaluation (recall measurable for the first time; artifact entity_sentence_eval.json)
        ("task2/src/entity_sentence_eval.py", []),
        ("task2/src/ablation_dictionary.py", ["--iter-compare"]),
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
    if task7_mode in ("rules", "both"):
        # static reproduction: explicitly select offline rules mode (prompt §2.3); no accidental network access due to a local config.json
        steps.append(("task7/src/run_tests.py", ["--rules"]))
    if task7_mode in ("llm", "both"):
        # dynamic acceptance: online LLM mode; artifacts written separately to *_llm.json / traces_llm/ (separated inside run_tests)
        steps.append(("task7/src/run_tests.py", []))
    return steps


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--task7", choices=["rules", "llm", "both"], default="rules",
                        help="任务7 验收模式：rules=离线静态复现（默认）；llm=在线动态验收；both=先离线再在线")
    args = parser.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
    steps = build_steps(args.task7)
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
