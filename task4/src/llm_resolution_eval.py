# -*- coding: utf-8 -*-
"""P3：LLM 受限消解 vs 规则消解（120 例黄金集）。

受限于与规则法同等的选项空间：
  - 候选池编号（pronoun_cases.jsonl 中每例的 candidates，POI/交通实体）；
  - SCENIC（回退到景区名，对应规则的"景区名"回退）；
  - NONE（无明确先行词）。
LLM 不允许输出候选池之外的实体名。温度 0，逐例调用，失败重试一次。

用法：python src/llm_resolution_eval.py [--limit 0]
输出：task4/output/llm_resolution_eval.json（总体/分类准确率 + 逐例原始回答）
注意：需 task7/config.json（不随仓库分发）。规则基线见 evaluation.json（0.475）。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
TASK7 = ROOT.parent / "task7"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(TASK7 / "src"))
from agent_cli import LLMClient  # noqa: E402

PROMPT = """你是中文指代消解助手。下面的游记片段中有一个代词需要消解。

代词：“{pronoun}”（类别：{cls}）
当前句：{sentence}
前一句：{prev}
前两句：{prev2}

候选池（只能从中选择，编号即答案）：
{candidates}

额外选项：
- SCENIC：代词指整个景区本身（候选都不对且语境是景区整体）
- NONE：无明确先行词（指代悬空、诗化指代或指前文未列出的内容）
{extra_options}
要求：判断代词实际指代的对象，只输出一个编号、SCENIC、NONE 或上述类型词，不要解释。"""


def fmt_candidates(cands: list[dict]) -> str:
    if not cands:
        return "（候选池为空）"
    return "\n".join(
        f"{i}. {c['name']}（{c['kind']}，{c['scope']}，距离{c['distance']}字符）"
        for i, c in enumerate(cands))


def parse_answer(text: str, n_cands: int) -> str:
    t = text.strip()
    up = t.upper()
    if "SCENIC" in up:
        return "SCENIC"
    for tok in ("OTHER_PERSON", "PARTY", "SET_PRECEDING", "SET_OTHER", "ROUTE", "FACILITY"):
        if tok in up:
            return tok
    if "NONE" in up:
        return "NONE"
    m = re.search(r"\d+", t)
    if m:
        idx = int(m.group())
        if 0 <= idx < n_cands:
            return f"CAND:{idx}"
    return "UNPARSED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 例（0=全部 120）")
    ap.add_argument("--extended", action="store_true",
                    help="v2：扩展选项空间（候选池+SCENIC+NONE+人称/集合/路线/设施类型词表，与规则法同词汇）")
    ap.add_argument("--output", type=str, default="",
                    help="输出文件名（默认 llm_resolution_eval.json；v2 用 llm_resolution_eval_v2.json）")
    args = ap.parse_args()

    llm = LLMClient(config_path=TASK7 / "config.json")
    if not llm.available:
        print("[abort] LLM 未配置（task7/config.json）")
        return 1

    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    cases = [json.loads(l) for l in (OUT / "pronoun_cases.jsonl").open(encoding="utf-8")]
    # 对齐校验（与 annotate_sample --score 同一策略）
    for gitem in gold:
        c = cases[gitem["case_index"]]
        for field in ("record_id", "pronoun", "doc_start", "doc_end"):
            assert c[field] == gitem[field], f"stale gold at {gitem['case_index']}"

    rows = gold[: args.limit] if args.limit else gold
    canon = {"CAND": None, "SCENIC": "景区名", "NONE": "无明确先行词"}  # CAND 的 kind 按候选补
    results, failures = [], []
    t0 = time.time()
    extended = args.extended
    for gitem in rows:
        c = cases[gitem["case_index"]]
        extra = ""
        if extended:
            extra = """- OTHER_PERSON：指服务角色/当地人/其他游客等他人（他们/她们/他们一家）
- PARTY：指作者及同行者（我们一行人等）
- SET_PRECEDING：指前文枚举的 POI 集合
- SET_OTHER：指前文的普通名词集合（如"72座峰""6顿餐"）
- ROUTE：指某条道路/线路本身
- FACILITY：指酒店/餐厅/民宿等设施"""
        prompt = PROMPT.format(
            pronoun=c["pronoun"], cls=c["pronoun_class"], sentence=c["sentence"],
            prev=c["prev_sentence"] or "（无）", prev2=c["prev2_sentence"] or "（无）",
            candidates=fmt_candidates(c.get("candidates", [])), extra_options=extra)
        answer_text, parsed = "", "UNPARSED"
        for attempt in (1, 2):
            try:
                answer_text = llm.complete("只输出编号、SCENIC 或 NONE，禁止解释。", prompt).strip()
                parsed = parse_answer(answer_text, len(c.get("candidates", [])))
                if parsed != "UNPARSED":
                    break
            except Exception as exc:  # 网络/限流：重试一次
                answer_text = f"ERROR:{exc}"
                time.sleep(2)
        if parsed == "UNPARSED":
            failures.append({"case_index": gitem["case_index"], "raw": answer_text[:120]})
        # 打分（与 annotate_sample --score 同一判定语义）
        if parsed.startswith("CAND:"):
            cand = c["candidates"][int(parsed.split(":")[1])]
            pred_kind = cand["kind"]
            pred_name = cand["name"]
        elif parsed == "SCENIC":
            pred_kind, pred_name = "景区名", c["scenic_area"]
        elif extended and parsed in ("OTHER_PERSON", "PARTY", "SET_PRECEDING", "SET_OTHER", "ROUTE", "FACILITY"):
            pred_kind = {"OTHER_PERSON": "他人", "PARTY": "同行者", "SET_PRECEDING": "前文POI集合",
                         "SET_OTHER": "名词集合", "ROUTE": "路线", "FACILITY": "设施"}[parsed]
            pred_name = parsed
        else:
            pred_kind, pred_name = "无明确先行词", "NONE"
        kind_map = {"POI": "POI", "交通": "交通", "景区名": "景区", "无明确先行词": "无"}
        kind_match = kind_map.get(pred_kind) == gitem["gold_kind"]
        if gitem["gold_kind"] in ("POI", "景区"):
            name_match = pred_name == gitem["gold_antecedent"]
        else:
            name_match = True
        results.append({
            "case_index": gitem["case_index"], "class": gitem["pronoun_class"],
            "gold": gitem["gold_antecedent"], "gold_kind": gitem["gold_kind"],
            "llm_answer_raw": answer_text[:60], "pred": pred_name, "pred_kind": pred_kind,
            "correct": bool(kind_match and name_match),
        })

    n = len(results)
    acc = sum(r["correct"] for r in results) / n
    by_class = {}
    for cls in ("locative", "object", "person", "set"):
        sub = [r for r in results if r["class"] == cls]
        by_class[cls] = {"n": len(sub), "accuracy": round(sum(r["correct"] for r in sub) / len(sub), 3)} if sub else {"n": 0, "accuracy": None}
    payload = {
        "mode": (f"llm-restricted-extended ({llm.model}, temperature=0, 选项空间=候选池+SCENIC+NONE+类型词表)"
                 if extended else
                 f"llm-restricted ({llm.model}, temperature=0, 选项空间=候选池+SCENIC+NONE)"),
        "n": n, "accuracy_overall": round(acc, 3), "accuracy_by_class": by_class,
        "failures": failures,
        "rule_baseline": json.loads((OUT / "evaluation.json").read_text(encoding="utf-8"))["accuracy_overall"],
        "elapsed_s": round(time.time() - t0, 1),
        "results": results,
    }
    out_name = args.output or ("llm_resolution_eval_v2.json" if extended else "llm_resolution_eval.json")
    (OUT / out_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"LLM 受限消解：{acc:.3f}（规则基线 {payload['rule_baseline']}），失败 {len(failures)} 例，耗时 {payload['elapsed_s']}s")
    print("分类:", by_class)
    return 0


if __name__ == "__main__":
    sys.exit(main())
