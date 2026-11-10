# -*- coding: utf-8 -*-
"""实验7 意图解析鲁棒性套件（规则模式，离线）。

- 同义改写：对验收场景查询做同义改写后解析，对比期望意图（16 例 + 1 项设计排除）
- 输入扰动：无关信息插入/句序变换/约束增删/否定表达变体/天数余量（10 例 base→变体配对）

期望值为开发 agent 逐例标注（AI 判读口径，已在报告声明）；输出 task7/output/。
运行：python src/intent_robustness.py [--g14|--g15]（默认两套件都跑，退出码=失败数>0）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from agent_cli import IntentParser

OUT = ROOT / "output"


# (id, 改写查询, 期望意图子集, 类别, 说明)
CASES_G14 = [

    ("V1", "陪岳父岳母去黄山玩两天，行程别太赶",
     {"visitor_type": "老人", "days": 2}, "check", "岳父岳母=老人，原场景用“带老人”"),
    ("V2", "和外婆一起游九寨沟，一日游怎么走",
     {"visitor_type": "老人", "days": 1}, "check", "外婆=老人"),
    ("V3", "带闺女去颐和园半天",
     {"visitor_type": "孩子", "days": 0.5}, "check", "闺女=孩子"),
    ("V4", "跟对象去黄山两日游",
     {"visitor_type": "情侣", "days": 2}, "check", "对象=情侣"),
    ("V5", "一家三口去九寨沟玩一天",
     {"visitor_type": "亲子", "days": 1}, "check", "一家=亲子（家庭出游）"),

    ("D1", "大半天时间逛颐和园，精华就好",
     {"days": 0.5}, "check", "大半天按半天档"),
    ("D2", "九寨沟玩两三天",
     {"days": 3}, "design", "模糊区间“两三天”：现行取先命中的三天档；区间推算超出规则解析范围"),
    ("D3", "只有三小时，颐和园快速逛一遍",
     {"days": 0.5}, "check", "三小时=半天档（数字+小时已覆盖，改汉字数词）"),

    ("A1", "九寨沟一日游，不想去原始森林",
     {"avoid": ["原始森林"]}, "check", "不想去=不要去"),
    ("A2", "黄山三天游，别安排莲花峰",
     {"avoid": ["莲花峰"], "days": 3}, "check", "别安排=别去"),
    ("A3", "九寨沟一日游，原始森林就不去了，人太多",
     {"avoid": ["原始森林"]}, "check", "POI后置否定“X就不去了”"),
    ("M1", "黄山两日游，光明顶是必去的",
     {"must": ["光明顶"], "days": 2}, "check", "POI后置“X是必去的”"),
    ("M2", "颐和园一日游，一定要逛佛香阁",
     {"must": ["佛香阁"]}, "check", "一定要逛=一定要去"),

    ("S1", "陪爸妈游九寨沟，不想太累",
     {"visitor_type": "老人", "special_has": "省力"}, "check", "不想太累=省力"),
    ("S2", "情侣黄山两日，想观日出",
     {"visitor_type": "情侣", "special_has": "看日出"}, "check", "观日出=看日出（日出词元已覆盖）"),

    ("T1", "过年的时候去黄山两天，要注意什么",
     {"month": 2}, "check", "过年=春节=2月档"),
    ("T2", "十二月底去九寨沟三天",
     {"month": 12, "days": 3}, "check", "十二月底=12月"),
]


def run_g14() -> int:
    parser = IntentParser(None)
    rows, n_fail = [], 0
    for cid, query, expect, kind, note in CASES_G14:
        intent = parser._parse_rules(query)
        got = {k: intent.get(k) for k in expect}
        mismatches = {}
        for k, want in expect.items():
            key = "special" if k == "special_has" else k
            actual = intent.get(key)
            if k == "special_has":
                ok = want in (actual or [])
            elif isinstance(want, list):
                ok = all(any(w in a or a in w for a in (actual or [])) for w in want) \
                    if actual else False
            else:
                ok = actual == want
            if not ok:
                mismatches[k] = {"want": want, "got": actual}
        passed = not mismatches
        if kind == "check" and not passed:
            n_fail += 1
        rows.append({"id": cid, "query": query, "kind": kind, "note": note,
                     "expect": expect, "parsed": got,
                     "passed": passed if kind == "check" else None,
                     "mismatches": mismatches})
        tag = "PASS" if (kind == "check" and passed) else \
              "DESIGN" if kind == "design" else "FAIL"
        print(f"{tag:6s} {cid} {query[:24]:26s} expect={expect} got={got}")
    report = {
        "title": "扩展：意图解析同义改写鲁棒性（实验7，规则模式）",
        "method": "对验收场景查询做同义改写后解析，对比期望意图；"
                  "期望值为 AI 标注（非人工判定，提示词 §7 口径声明）",
        "n_cases": len(CASES_G14), "n_check": sum(1 for c in CASES_G14 if c[3] == "check"),
        "n_design_excluded": sum(1 for c in CASES_G14 if c[3] == "design"),
        "n_fail": n_fail,
        "cases": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "paraphrase_g14.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_check": report["n_check"], "n_fail": n_fail,
                      "n_design": report["n_design_excluded"]}, ensure_ascii=False))
    return 1 if n_fail else 0


# (id, base 查询, 变体查询, 期望意图（变体须满足）, 期望保持字段（base 与 variant 须一致）, 类别)
CASES_G15 = [
    ("N1", "带老人去颐和园玩半天，腿脚不方便",
     "最近听朋友说颐和园人特别多。带老人去颐和园玩半天吧，老人腿脚不太方便，麻烦推荐下",
     {"visitor_type": "老人", "days": 0.5}, ["scenic", "days", "visitor_type"], "无关信息"),
    ("N2", "带孩子九寨沟一日游",
     "带娃去九寨沟玩一天，天气据说不错",
     {"visitor_type": "孩子", "days": 1}, ["scenic", "days", "visitor_type"], "无关信息"),
    ("W1", "情侣黄山两日游，想看日出",
     "想看日出，黄山两日游，情侣出行",
     {"visitor_type": "情侣", "days": 2, "special_has": "看日出"},
     ["scenic", "days", "visitor_type"], "句序变换"),
    ("W2", "九寨沟一日游，不要去原始森林",
     "原始森林不要去，九寨沟一日游",
     {"avoid": ["原始森林"], "days": 1}, ["scenic", "days"], "句序变换"),
    ("A1", "黄山两天，避开莲花峰",
     "黄山两天，12月去，避开莲花峰",
     {"days": 2, "avoid": ["莲花峰"], "month": 12}, ["scenic", "days", "avoid"], "约束增删"),
    ("A2", "九寨沟一日游",
     "我们几个朋友九寨沟一日游，走路要少",
     {"days": 1, "special_has": "省力"}, ["scenic", "days"], "约束增删"),
    ("P1", "九寨沟一日游，不要去原始森林",
     "九寨沟一日游，除了原始森林都可以",
     {"avoid": ["原始森林"], "days": 1}, ["scenic", "days"], "否定表达变体"),
    ("P2", "九寨沟一日游，不要去原始森林",
     "九寨沟一日游，原始森林就别安排了",
     {"avoid": ["原始森林"], "days": 1}, ["scenic", "days"], "否定表达变体"),
    ("D1", "带老人去颐和园玩半天",
     "带老人去颐和园，就半天时间",
     {"days": 0.5, "visitor_type": "老人"}, ["scenic", "visitor_type"], "天数余量"),
    ("D2", "情侣黄山两日游",
     "情侣黄山玩两天，时间大概48小时",
     {"days": 2, "visitor_type": "情侣"}, ["scenic", "visitor_type"], "天数余量"),
]


def run_g15() -> int:
    parser = IntentParser(None)
    rows, n_fail = [], 0
    for cid, base_q, var_q, expect, keep_fields, kind in CASES_G15:
        base = parser._parse_rules(base_q)
        intent = parser._parse_rules(var_q)
        mismatches = {}
        for k, want in expect.items():
            key = "special" if k == "special_has" else k
            actual = intent.get(key)
            if k == "special_has":
                ok = want in (actual or [])
            elif isinstance(want, list):
                ok = bool(actual) and all(
                    any(w in a or a in w for a in actual) for w in want)
            else:
                ok = actual == want
            if not ok:
                mismatches[k] = {"want": want, "got": actual}
        drift = {}
        for f in keep_fields:
            b, v = base.get(f), intent.get(f)
            if isinstance(b, list) and isinstance(v, list):
                same = {x.split(":")[0] if isinstance(x, str) else x for x in b} \
                    == {x.split(":")[0] if isinstance(x, str) else x for x in v}
            else:
                same = b == v
            if not same:
                drift[f] = {"base": b, "variant": v}
        passed = not mismatches and not drift
        if not passed:
            n_fail += 1
        rows.append({"id": cid, "kind": kind, "base_query": base_q, "variant_query": var_q,
                     "expect": expect, "parsed": {k: intent.get(k) for k in expect},
                     "field_drift": drift, "passed": passed})
        tag = "PASS" if passed else "FAIL"
        print(f"{tag} {cid} [{kind}] {var_q[:26]:28s} mismatches={mismatches or '-'} drift={drift or '-'}")
    report = {
        "title": "输入扰动稳定性：无关信息/句序变换/约束增删/否定变体（实验7，规则模式）",
        "method": "base 与变体查询配对：变体须满足期望意图，且 keep_fields 相对 base 无漂移；"
                  "期望值为 AI 标注（非人工判定，§7 口径声明）",
        "n_cases": len(CASES_G15), "n_fail": n_fail, "cases": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "robustness_g15.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_cases": len(CASES_G15), "n_fail": n_fail}, ensure_ascii=False))
    return 1 if n_fail else 0


def main() -> int:
    fails = 0
    if "--g14" not in sys.argv:
        fails += run_g14() or 0
    if "--g15" not in sys.argv:
        fails += run_g15() or 0
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
