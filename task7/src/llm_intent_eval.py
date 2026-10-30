# -*- coding: utf-8 -*-
"""P6：LLM 模式 vs 规则模式——意图解析一致率与正确率实测。

查询集：8 个既有测试场景 + 12 个变体问句（预先登记期望意图作为真值）。
三种口径：
  1. 规则模式准确率（期望意图为真值）；
  2. LLM 模式准确率（同上）；
  3. 两模式逐字段一致率（scenic/visitor_type/days/special）。
输出：task7/output/llm_intent_eval.json。需 task7/config.json。
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(ROOT / "src"))
from agent_cli import IntentParser, LLMClient  # noqa: E402

# 期望意图由本文件预先登记（登记于运行前，非看结果后填写）
BATTERY = [
    # —— 8 个既有测试场景 ——
    ("带老人去颐和园玩半天，腿脚不方便，走省力的路线", {"scenic": "颐和园", "visitor_type": "老人", "days": 0.5, "special": ["省力"]}),
    ("带孩子九寨沟一日游，怎么安排？", {"scenic": "九寨沟", "visitor_type": "孩子", "days": 1, "special": []}),
    ("情侣黄山两日游，想看日出", {"scenic": "黄山", "visitor_type": "情侣", "days": 2, "special": ["看日出"]}),
    ("只有3小时，颐和园快速逛一遍精华", {"scenic": "颐和园", "visitor_type": None, "days": 0.5, "special": []}),
    ("帮我规划故宫一日游", {"scenic": "未知", "visitor_type": None, "days": 1, "special": []}),
    ("半天时间在黄山看日出再下西海大峡谷", {"scenic": "黄山", "visitor_type": None, "days": 0.5, "special": ["看日出"]}),
    ("九寨沟一日游，想去原始森林看看", {"scenic": "九寨沟", "visitor_type": None, "days": 1, "special": []}),
    ("九寨沟从长海出来怎么走回诺日朗中心？", {"scenic": "九寨沟", "visitor_type": None, "days": 1, "special": []}),
    # —— 12 个变体问句 ——
    ("带着爸妈去九寨沟玩两天，老人腿脚不好", {"scenic": "九寨沟", "visitor_type": "老人", "days": 2, "special": ["省力"]}),
    ("颐和园拍照的好机位有哪些", {"scenic": "颐和园", "visitor_type": None, "days": 1, "special": ["拍照片"]}),
    ("黄山一日游怎么走最省力？", {"scenic": "黄山", "visitor_type": None, "days": 1, "special": ["省力"]}),
    ("我们两个人蜜月旅行去九寨沟，三天", {"scenic": "九寨沟", "visitor_type": "情侣", "days": 3, "special": []}),
    ("第一次去颐和园，帮忙规划下", {"scenic": "颐和园", "visitor_type": "初次游览", "days": 1, "special": []}),
    ("西湖一日游攻略", {"scenic": "未知", "visitor_type": None, "days": 1, "special": []}),
    ("黄山看云海和日出，玩一天半", {"scenic": "黄山", "visitor_type": None, "days": 1.5, "special": ["看日出"]}),
    ("推婴儿车逛颐和园方便吗", {"scenic": "颐和园", "visitor_type": "亲子", "days": 1, "special": []}),
    ("九寨沟秋天赏红叶两天怎么安排", {"scenic": "九寨沟", "visitor_type": None, "days": 2, "special": ["红叶"]}),
    ("带娃爬黄山累不累", {"scenic": "黄山", "visitor_type": "孩子", "days": 1, "special": []}),
    ("颐和园半天够吗？想避开人流", {"scenic": "颐和园", "visitor_type": None, "days": 0.5, "special": ["避开人流"]}),
    ("成都出发九寨沟两日游带孩子和老人", {"scenic": "九寨沟", "visitor_type": "老人", "days": 2, "special": []}),
]


def score(intent: dict, expect: dict) -> tuple[bool, dict]:
    fields = {}
    for k, v in expect.items():
        if k == "special":
            fields[k] = sorted(intent.get(k) or []) == sorted(v)
        elif k == "days":
            fields[k] = abs(float(intent.get(k) or 0) - float(v)) < 1e-6
        else:
            fields[k] = intent.get(k) == v
    return all(fields.values()), fields


def main() -> int:
    llm = LLMClient(config_path=ROOT / "config.json")
    if not llm.available:
        print("[abort] LLM 未配置")
        return 1
    rule_parser = IntentParser(None)
    llm_parser = IntentParser(llm)

    rows, t0 = [], time.time()
    for query, expect in BATTERY:
        dummy: list = []
        i_rule = rule_parser.parse(query, dummy)
        i_llm = llm_parser.parse(query, dummy)  # llm 可用时 parse 返回混合模式结果
        ok_rule, f_rule = score(i_rule, expect)
        ok_llm, f_llm = score(i_llm, expect)
        agree = all(i_rule.get(k) == i_llm.get(k) for k in ("scenic", "visitor_type", "days", "special"))
        rows.append({"query": query, "expect": expect,
                     "rule": i_rule, "llm": i_llm,
                     "rule_ok": ok_rule, "llm_ok": ok_llm, "modes_agree": agree,
                     "fields_rule": f_rule, "fields_llm": f_llm})

    n = len(rows)
    payload = {
        "model": llm.model,
        "mode": "hybrid（规则精确字段优先 + LLM 补缺省）vs rules",
        "n": n,
        "rule_accuracy": round(sum(r["rule_ok"] for r in rows) / n, 3),
        "llm_accuracy": round(sum(r["llm_ok"] for r in rows) / n, 3),
        "mode_agreement": round(sum(r["modes_agree"] for r in rows) / n, 3),
        "field_agreement": {k: round(sum(1 for r in rows if r["rule"].get(k) == r["llm"].get(k)) / n, 3)
                            for k in ("scenic", "visitor_type", "days", "special")},
        "elapsed_s": round(time.time() - t0, 1),
        "rows": rows,
    }
    (OUT / "llm_intent_eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"规则正确率 {payload['rule_accuracy']} | LLM 正确率 {payload['llm_accuracy']} | 模式一致率 {payload['mode_agreement']}")
    print("字段级一致率:", payload["field_agreement"])
    for r in rows:
        if not r["llm_ok"] or not r["modes_agree"]:
            print(f"  [分歧] {r['query'][:26]} | 期望{r['expect']} | llm={r['llm']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
