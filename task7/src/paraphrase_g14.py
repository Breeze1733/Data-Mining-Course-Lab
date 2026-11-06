"""实验7 G14 扩展：意图解析的同义改写鲁棒性检验。

对 14 个验收场景的查询做同义改写（同一意图的不同说法），在规则模式下解析，
对比期望意图字段。目的：发现"换个说法就解析错/漏"的脆弱点，驱动解析规则补强。

期望值为 AI 标注（提示词 §7 声明口径：AI 判定须标注为 AI，不冒充人工判定）。
两类判定：
- check     必须通过：有明确证据的同义表达，解析失败即缺陷（驱动修复）
- design    设计排除：歧义/超范围表达（如"两三天"取档、"周五到周日"需日期推算），
            记录当前行为与豁免理由，不计入失败

输出 task7/output/paraphrase_g14.json。
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
CASES = [
    # ── 人群同义 ────────────────────────────────────────────────
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
    # ── 天数/时段同义 ───────────────────────────────────────────
    ("D1", "大半天时间逛颐和园，精华就好",
     {"days": 0.5}, "check", "大半天按半天档"),
    ("D2", "九寨沟玩两三天",
     {"days": 3}, "design", "模糊区间“两三天”：现行取先命中的三天档；区间推算超出规则解析范围"),
    ("D3", "只有三小时，颐和园快速逛一遍",
     {"days": 0.5}, "check", "三小时=半天档（数字+小时已覆盖，改汉字数词）"),
    # ── 不去/必去同义 ───────────────────────────────────────────
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
    # ── 特殊需求同义 ────────────────────────────────────────────
    ("S1", "陪爸妈游九寨沟，不想太累",
     {"visitor_type": "老人", "special_has": "省力"}, "check", "不想太累=省力"),
    ("S2", "情侣黄山两日，想观日出",
     {"visitor_type": "情侣", "special_has": "看日出"}, "check", "观日出=看日出（日出词元已覆盖）"),
    # ── 月份同义 ────────────────────────────────────────────────
    ("T1", "过年的时候去黄山两天，要注意什么",
     {"month": 2}, "check", "过年=春节=2月档"),
    ("T2", "十二月底去九寨沟三天",
     {"month": 12, "days": 3}, "check", "十二月底=12月"),
]


def main() -> int:
    parser = IntentParser(None)
    rows, n_fail = [], 0
    for cid, query, expect, kind, note in CASES:
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
        "title": "G14 扩展：意图解析同义改写鲁棒性（实验7，规则模式）",
        "method": "对验收场景查询做同义改写后解析，对比期望意图；"
                  "期望值为 AI 标注（非人工判定，提示词 §7 口径声明）",
        "n_cases": len(CASES), "n_check": sum(1 for c in CASES if c[3] == "check"),
        "n_design_excluded": sum(1 for c in CASES if c[3] == "design"),
        "n_fail": n_fail,
        "cases": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "paraphrase_g14.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_check": report["n_check"], "n_fail": n_fail,
                      "n_design": report["n_design_excluded"]}, ensure_ascii=False))
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
