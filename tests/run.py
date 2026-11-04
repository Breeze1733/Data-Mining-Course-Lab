"""Offline rebuild from the committed canonical corpus; never collects web data.

python run.py [--task7 rules|llm|both]

任务7 验收模式（提示词 §2.3）：
  rules  默认。离线规则模式，静态复现口径（--rules 显式传入，不因本机 config.json 联网）。
  llm    在线动态验收：调用配置的 LLM 出行程与回答，产物单独写入 *_llm.json / traces_llm/，
         不覆盖离线验收证据；需要 task7/config.json。
  both   先离线静态复现，再在线动态验收。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_steps(task7_mode: str) -> list:
    steps = [
        # 单元测试先行：链路重建前先保证基础语义未被破坏（P15）
        ("__unittest__", []),
        # B03 漏检驱动的词典/时间规则扩充（幂等，须先于 build_dictionary）
        ("task2/src/expand_dictionary_b03.py", []),
        ("task2/src/build_dictionary.py", []),
        ("task2/src/extract_entities.py", ["--iteration", "baseline"]),
        ("task2/src/extract_entities.py", ["--iteration", "refined"]),
        ("task2/src/visualize.py", ["--iteration", "baseline"]),
        ("task2/src/visualize.py", ["--iteration", "refined"]),
        ("task2/src/spot_check.py", ["--reconcile"]),
        # B01 句级实体评测（查全率首次可测，产物 entity_sentence_eval.json）
        ("task2/src/entity_sentence_eval.py", []),
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
    ]
    if task7_mode in ("rules", "both"):
        # 静态复现：显式选择离线规则模式（提示词 §2.3），不因本机 config.json 意外联网
        steps.append(("task7/src/run_tests.py", ["--rules"]))
    if task7_mode in ("llm", "both"):
        # 动态验收：在线 LLM 模式，产物单独写入 *_llm.json / traces_llm/（run_tests 内部分离）
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
