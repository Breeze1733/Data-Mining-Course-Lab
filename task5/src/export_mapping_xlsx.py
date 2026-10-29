"""实验5：映射表 Excel 导出（mapping_table.json → conditional_mapping_table.xlsx）。"""
import json
import sys
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
sys.stdout.reconfigure(encoding="utf-8")


def main():
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    stats = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))
    review = json.loads((OUT / "review_summary.json").read_text(encoding="utf-8"))

    wb = Workbook()
    ws = wb.active
    ws.title = "条件-建议映射表"
    headers = ["条件类型", "条件描述", "建议内容", "触发词", "抽取模式", "景区", "频次", "来源记录（前5）"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    order = {"人群": 0, "天气": 1, "时间": 2, "装备": 3, "预约票务": 4, "交通": 5,
             "体力安全": 6, "一般": 7, "其他": 8}
    for m in sorted(mapping, key=lambda x: (order.get(x["condition_type"], 9), -x["frequency"])):
        ws.append([m["condition_type"], m["condition_text"][:120], m["suggestion_text"][:200],
                   m["trigger"], m["pattern"], m["scenic_area"], m["frequency"],
                   "；".join(m["sources"][:5])])
    for col, w in zip("ABCDEFGH", (10, 34, 44, 8, 14, 9, 7, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("统计与抽检")
    ws2.append(["指标", "值"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    for k in ("raw_pairs", "after_dedup", "duplicates_merged"):
        ws2.append([k, stats[k]])
    ws2.append(["by_pattern", json.dumps(stats["by_pattern"], ensure_ascii=False)])
    ws2.append(["by_condition_type", json.dumps(stats["by_condition_type"], ensure_ascii=False)])
    ws2.append(["by_scenic", json.dumps(stats["by_scenic"], ensure_ascii=False)])
    ws2.append(["人工抽检", json.dumps(review["verdicts"], ensure_ascii=False) +
                f"（n={review['n']}，严格正确 {review['verdicts'].get('correct',0)/review['n']:.0%}）"])
    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 90

    out = OUT / "conditional_mapping_table.xlsx"
    wb.save(out)
    print(json.dumps({"output": out.as_posix(), "rows": len(mapping)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
