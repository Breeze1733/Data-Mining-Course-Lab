"""Export the deduplicated conditional-advice mapping table to a reviewable Excel workbook.

Input : task5/output/mapping_table.json + extraction_stats.json
Output: task5/output/mapping_table.xlsx
Sheets: 映射表 (one row per mapping entry), 人群统计 (visitor-type × scenic),
        条件类型统计 (condition-type × scenic × polarity), 字段说明.
Run   : python task5/src/export_mapping_xlsx.py  (repo root)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

sys.stdout.reconfigure(encoding="utf-8")

HEADER_FILL = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")


def crowd_subtype_label(row: dict) -> str:
    text = row.get("condition_text") or row.get("condition_label") or ""
    for w in ("老人", "孩子", "小孩", "儿童", "婴儿", "亲子", "带娃", "情侣", "夫妻", "孕妇",
              "腿脚", "体力", "新手", "第一次", "学生", "家庭", "恐高", "晕车"):
        if w in text:
            return w
    return "未细分"


def main() -> int:
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    stats = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))

    wb = Workbook()

    # Sheet 1: the mapping table itself, ordered for human review.
    ws = wb.active
    ws.title = "映射表"
    headers = ["条件类型", "条件描述", "建议内容", "来源景区", "极性", "抽取模式", "触发词",
               "频次", "来源记录数", "来源记录", "原始句"]
    ws.append(headers)
    order = {"黄山": 0, "九寨沟": 1, "颐和园": 2}
    rows = sorted(mapping, key=lambda r: (order.get(r["scenic_area"], 9), r["condition_type"], -r["frequency"]))
    for r in rows:
        ws.append([
            r["condition_type"],
            r["condition_text"] or f"（无显式条件：{r['condition_label'] or r['condition_absent_reason']}）",
            r["suggestion_text"],
            r["scenic_area"],
            r["polarity"],
            r["pattern"],
            r["trigger"],
            r["frequency"],
            len(r["sources"]),
            "、".join(r["sources"][:5]) + ("…" if len(r["sources"]) > 5 else ""),
            r["sentence"],
        ])
    widths = [10, 30, 42, 9, 7, 10, 12, 6, 9, 34, 56]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = HEADER_FILL
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP
    ws.freeze_panes = "A2"

    # Sheet 2: visitor-type breakdown (任务书: 按游客类型分组统计).
    ws2 = wb.create_sheet("人群统计")
    crowd_scenic: dict[str, Counter] = defaultdict(Counter)
    for r in mapping:
        if r["condition_type"] == "人群":
            crowd_scenic[crowd_subtype_label(r)][r["scenic_area"]] += r["frequency"]
    scenics = ["黄山", "九寨沟", "颐和园"]
    ws2.append(["游客类型", *scenics, "合计"])
    total = Counter()
    for label in sorted(crowd_scenic, key=lambda k: -sum(crowd_scenic[k].values())):
        counts = [crowd_scenic[label].get(s, 0) for s in scenics]
        for c, v in zip(scenics, counts):
            total[c] += v
        ws2.append([label, *counts, sum(counts)])
    ws2.append(["合计", *[total[s] for s in scenics], sum(total.values())])
    for i, w in enumerate([14, 10, 10, 10, 8], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    for cell in ws2[1]:
        cell.font = HEADER_FILL

    # Sheet 3: condition-type breakdown by scenic area and polarity.
    ws3 = wb.create_sheet("条件类型统计")
    type_scenic: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for r in mapping:
        type_scenic[(r["condition_type"], r["scenic_area"])][r["polarity"]] += r["frequency"]
    ws3.append(["条件类型", "景区", "正向建议", "负向建议(避雷)", "合计"])
    for ctype in sorted({k[0] for k in type_scenic}, key=lambda k: -sum(sum(v.values()) for (t, _), v in type_scenic.items() if t == k)):
        for scenic in scenics:
            c = type_scenic.get((ctype, scenic), Counter())
            ws3.append([ctype, scenic, c.get("POS", 0), c.get("NEG", 0), c.get("POS", 0) + c.get("NEG", 0)])
    for i, w in enumerate([12, 9, 12, 14, 8], start=1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    for cell in ws3[1]:
        cell.font = HEADER_FILL

    # Sheet 4: provenance of this workbook.
    ws4 = wb.create_sheet("字段说明")
    notes = [
        ["生成脚本", "task5/src/export_mapping_xlsx.py"],
        ["数据来源", "task1/data/processed/dataset_clean.jsonl（267 条，经 task4 句级景区归属过滤）"],
        ["抽取规则", "task5/src/extract_conditionals.py（触发词规则 + 边界修补 + 非游览建议过滤 + 建议性结构门）"],
        ["原始抽取对", stats["raw_pairs"]],
        ["过滤剔除对", stats["filtered_pairs"]],
        ["去重后映射行", stats["after_dedup"]],
        ["去重键", stats["dedup_key_version"]],
        ["字段：条件类型", "条件文本的规则分类（天气/人群/装备/预约票务/交通/体力安全/时间/住宿/美食/拍照/其他）；无显式条件时为建议侧推断类型"],
        ["字段：条件描述", "句中逐字条件片段；无显式条件时标注缺省原因或标签"],
        ["字段：建议内容", "建议部分逐字片段（多建议句已切分）"],
        ["字段：频次", "该条件→建议对在语料中的出现次数（去重前对数）"],
    ]
    for row in notes:
        ws4.append(row)
    ws4.column_dimensions["A"].width = 16
    ws4.column_dimensions["B"].width = 110
    ws4["A1"].font = HEADER_FILL

    target = OUT / "mapping_table.xlsx"
    wb.save(target)
    print(json.dumps({"output": target.as_posix(), "rows": len(rows),
                      "sheets": wb.sheetnames}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
