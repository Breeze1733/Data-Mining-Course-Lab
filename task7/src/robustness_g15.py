"""实验7 G15：意图解析对输入扰动的稳定性检验。

在 G14（同义改写）基础上，按 §5 G15 扩展四类扰动：
- 无关信息插入（前后加与意图无关的句子）
- 句序变换（约束子句换序）
- 约束增删（追加月份/人群等新约束，原有字段须保持）
- 否定表达变体（"除了X都行"式排除）

期望值为 AI 标注（§7 口径声明）。规则模式解析，对比期望意图字段；
对 base→variant 的字段漂移做配对检查：已有字段不得因扰动漂移。
输出 task7/output/robustness_g15.json。
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

# (id, base 查询, 变体查询, 期望意图（变体须满足）, 期望保持字段（base 与 variant 须一致）, 类别)
CASES = [
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


def main() -> int:
    parser = IntentParser(None)
    rows, n_fail = [], 0
    for cid, base_q, var_q, expect, keep_fields, kind in CASES:
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
        "title": "G15 输入扰动稳定性：无关信息/句序变换/约束增删/否定变体（实验7，规则模式）",
        "method": "base 与变体查询配对：变体须满足期望意图，且 keep_fields 相对 base 无漂移；"
                  "期望值为 AI 标注（非人工判定，§7 口径声明）",
        "n_cases": len(CASES), "n_fail": n_fail, "cases": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "robustness_g15.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_cases": len(CASES), "n_fail": n_fail}, ensure_ascii=False))
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
