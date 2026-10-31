# -*- coding: utf-8 -*-
"""P1 方案C：LLM few-shot 句级叙述归属，vs 方案A（记录级标签 0.457）/方案B（特征规则 0.796）。

与 U5 完全同口径：同一 495 句黄金（sentence_attribution.jsonl）、同一 seed=42 对半划分。
few-shot 示例为本次新写的合成例（不取自 495 句，避免泄漏）；给 LLM 的信息包括
句子本身与记录级主景区标签（同方案B可用的特征）。temperature=0。

用法：python src/llm_attribution_eval.py [--limit 0]
输出：task4/output/attribution/llm_attribution_eval.json
需 task7/config.json；规则/特征基线见 attribution_eval.json。
"""
from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTR = ROOT / "output/attribution"
TASK7 = ROOT.parent / "task7"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(TASK7 / "src"))
from agent_cli import LLMClient  # noqa: E402

LABELS = ["黄山", "九寨沟", "颐和园", "景区外", "无法判断"]

RUBRIC = """判定口径（五选一）：
- 景区内（黄山/九寨沟/颐和园）：句子叙述焦点是该景区范围内的游览要素——景点、园内交通（索道/观光车/步道）、
  园内设施（山上酒店/园内厕所）、门票与开放规则、官方路线与时段建议。
- 景区外：焦点在景区之外——周边联游景区、山下/沟口/市区酒店餐饮购物、往返大交通（航班/高铁/自驾抵达）、
  平台广告、纯城市游内容。
- 无法判断：代词悬空且无景区线索、纯表情/语气碎片、真并列无主次的多景区句。
提示：山上/园内住宿算景区内，沟口/山下/市区算景区外；品牌名可能含景区名（如"黄山毛尖"是茶）。"""

FEWSHOT = """示例：
句：索道排队两小时，下山后腿都软了。（记录主景区：黄山）→ 黄山
句：晚上住在沟口的酒店，老板推荐了第二天的路线。（记录主景区：九寨沟）→ 景区外
句：从北宫门入园，先逛苏州街再爬万寿山。（记录主景区：颐和园）→ 颐和园
句：机票是提前两个月订的，比高铁便宜不少。（记录主景区：黄山）→ 景区外
句：然后再往前走一点就到了。（记录主景区：九寨沟）→ 无法判断
"""


def build_prompt(sent: str, record_label: str) -> str:
    return f"""{RUBRIC}

{FEWSHOT}
现在判断下面这句（只输出 黄山/九寨沟/颐和园/景区外/无法判断 之一，禁止解释）：
句：{sent}（记录主景区：{record_label}）→"""


def parse_label(text: str) -> str:
    t = text.strip()
    for lab in LABELS:
        if lab in t:
            return lab
    return "UNPARSED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    llm = LLMClient(config_path=TASK7 / "config.json")
    if not llm.available:
        print("[abort] LLM 未配置")
        return 1

    gold = [json.loads(l) for l in (ATTR / "sentence_attribution.jsonl").open(encoding="utf-8")]
    rows = gold[: args.limit] if args.limit else gold

    rng = random.Random(42)
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    half = len(rows) // 2
    tune_ids, hold_ids = set(idx[:half]), set(idx[half:])

    results, failures = [], []
    t0 = time.time()
    for i, g in enumerate(rows):
        ans = llm_out = "UNPARSED"
        for _ in (1, 2):
            try:
                llm_out = llm.complete(
                    "只输出一个标签，禁止解释。", build_prompt(g["sentence"], g["scenic_area"]),
                    temperature=0).strip()
                ans = parse_label(llm_out)
                if ans != "UNPARSED":
                    break
            except Exception as exc:
                llm_out = f"ERROR:{exc}"
                time.sleep(2)
        if ans == "UNPARSED":
            failures.append({"sid": g["sid"], "raw": llm_out[:100]})
        results.append({"sid": g["sid"], "gold": g["label"], "pred": ans,
                        "half": "tune" if i in tune_ids else "holdout",
                        "record_label": g["scenic_area"], "raw": llm_out[:40]})

    def acc(ids: set[int]) -> float:
        sub = [r for i, r in enumerate(results) if i in ids]
        return sum(1 for r in sub if r["pred"] == r["gold"]) / len(sub)

    # 方案A/B 基线引用（attribution_eval.json 由 attribute_sentences.py --evaluate 生成）
    base = json.loads((ATTR / "attribution_eval.json").read_text(encoding="utf-8"))
    payload = {
        "mode": f"llm-fewshot ({llm.model}, temperature=0, 合成few-shot示例5条)",
        "n": len(results), "failures": len(failures),
        "tune_acc": round(acc(tune_ids), 4), "holdout_acc": round(acc(hold_ids), 4),
        "full_acc": round(acc(set(range(len(results)))), 4),
        "baseline_A": base["full"]["A"]["acc"], "baseline_B": base["full"]["B"]["acc"],
        "baseline_B_holdout": base["holdout"]["B"]["acc"],
        "elapsed_s": round(time.time() - t0, 1),
        "failures_detail": failures,
        "results": results,
    }
    (ATTR / "llm_attribution_eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"方案C LLM: tune {payload['tune_acc']} / holdout {payload['holdout_acc']} / 全量 {payload['full_acc']}"
          f"（A={payload['baseline_A']}, B={payload['baseline_B']}，失败 {len(failures)}，{payload['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
