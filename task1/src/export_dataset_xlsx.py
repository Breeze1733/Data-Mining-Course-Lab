"""把清洗管线的输出整理为人类可读的 Excel 工作簿 data/collected/scenic_guide_dataset.xlsx。

输入：data/processed/ 下 preprocess.py 的产物。单元格上限 32767 字符，
超长字段截断存放，完整内容以 data/processed/dataset_clean.{jsonl,csv} 为准。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/processed"
OUT = ROOT / "data/collected/scenic_guide_dataset.xlsx"
EXCEL_LIMIT = 32767
EXCERPT_LIMIT = 1200

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
HEADER_FONT = Font(bold=True)

RULE_NOTES = {
    "html_tags_removed": "HTML 标签配对剔除（块级标签转为换行）",
    "html_noncontent_blocks_removed": "script/style/隐藏块等无内容区域整块跳过",
    "html_comments_removed": "HTML 注释剔除",
    "html_entities_decoded": "HTML 实体解码（含二次转义）",
    "fullwidth_characters_normalized": "全角 ASCII/全角空格归一（保留①Ⅰ²℃等记号）",
    "urls_removed": "URL 剔除",
    "private_or_surrogate_characters_removed": "私用区/代理对字符剔除",
    "control_and_zero_width_characters_removed": "控制符与零宽字符剔除",
    "emoji_and_decorative_characters_removed": "表情与装饰符号剔除（保留路线箭头与语义符号）",
    "horizontal_whitespace_runs_normalized": "水平空白串归一为单空格",
    "blank_lines_removed": "空行剔除",
    "metadata_lines_removed": "平台元数据行剔除（点赞/分享/Copyright 等）",
    "duplicate_long_paragraphs_removed": "≥40 字重复长段落剔除（同文多副本抓取）",
    "platform_notice_lines_removed": "平台公告行剔除（游记业务停运通知）",
    "trip_metadata_labels_removed": "行程元数据标签行剔除（出发时间/行程天数等）",
    "trip_metadata_values_removed": "行程元数据值行剔除（与标签成对）",
    "player_timestamp_lines_removed": "内嵌播放器时间戳行剔除（00:00/00:00）",
}


def sheet_header(ws, headers):
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    ws.freeze_panes = "A2"


def clip(value, limit=EXCEL_LIMIT):
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 30] + f"…[截断，共{len(value)}字符，完整内容见 dataset_clean.jsonl]"
    return value


def main() -> int:
    if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rows = [json.loads(line) for line in (PROCESSED / "dataset_clean.jsonl").open(encoding="utf-8")]
    rejected = [json.loads(line) for line in (PROCESSED / "rejected_records.jsonl").open(encoding="utf-8")]
    examples = json.loads((PROCESSED / "cleaning_examples.json").read_text(encoding="utf-8"))
    report = json.loads((PROCESSED / "quality_report.json").read_text(encoding="utf-8"))

    wb = Workbook()

    # ── Sheet 1: 数据总览 ──────────────────────────────────────────
    ws = wb.active
    ws.title = "数据总览"
    sheet_header(ws, ["指标", "值"])
    overview = [
        ("输入记录数", report["input_records"]),
        ("清洗后保留", report["accepted_records"]),
        ("拒绝记录数", report["rejected_records"]),
        ("景区覆盖", "黄山 / 九寨沟 / 颐和园"),
        ("每个景区 ≥1 官方路线 + ≥5 篇游记", "全部满足" if report["main_target_met"] else "未满足"),
        ("来源平台分布", "；".join(f"{k} {v} 条" for k, v in report["profile"]["source_platforms"].items())),
        ("清洗后总字符数", report["profile"]["clean_characters_total"]),
        ("清洗后长度（最短/中位/最长）",
         f"{report['profile']['clean_length_min']} / {report['profile']['clean_length_median']} / {report['profile']['clean_length_max']}"),
        ("精确重复内容（保留集中）", report["duplicate_clean_contents_in_accepted"]),
        ("近似重复对（仅标记不删除）", len(report["near_duplicate_pairs"])),
    ]
    for k, v in overview:
        ws.append([k, v])
    ws.append([])
    ws.append(["分景区 × 平台覆盖"])
    sheet_header(ws, ["景区", "官方路线", "携程游记", "小红书笔记", "合计"])
    for area, cov in report["coverage_by_scenic_area"].items():
        plat = cov["platforms"]
        ws.append([area, plat.get("官方", 0), plat.get("携程游记", 0), plat.get("小红书", 0), cov["total"]])
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 50

    # ── Sheet 2: 清洗后数据集 ──────────────────────────────────────
    ws = wb.create_sheet("清洗后数据集")
    cols = ["record_id", "scenic_area", "source_platform", "text_type", "title", "author",
            "published_at", "source_url", "clean_char_count", "clean_nonspace_char_count",
            "retention_ratio", "quality_flags", "clean_content"]
    sheet_header(ws, cols)
    for row in rows:
        ws.append([clip(row.get(c, "") if c != "quality_flags" else "；".join(row.get("quality_flags", [])))
                   for c in cols])
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 9
    ws.column_dimensions["C"].width = 11
    ws.column_dimensions["D"].width = 13
    ws.column_dimensions["E"].width = 30
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 40
    ws.column_dimensions["M"].width = 60

    # ── Sheet 3: 清洗前后样例 ──────────────────────────────────────
    ws = wb.create_sheet("清洗前后样例")
    sheet_header(ws, ["record_id", "景区", "平台", "标题", "raw_format", "清洗前（节选）", "清洗后（节选）", "清洗规则命中"])
    platform_of = {r["record_id"]: r["source_platform"] for r in rows}
    picked, seen_key = [], set()
    for ex in examples:
        key = (ex["scenic_area"], platform_of.get(ex["record_id"], ""))
        if key not in seen_key:
            seen_key.add(key)
            picked.append(ex)
    for ex in examples:
        if len(picked) >= 12:
            break
        if ex not in picked:
            picked.append(ex)
    for ex in picked[:12]:
        rules = "；".join(f"{k}×{v}" for k, v in ex["cleaning_counts"].items() if v)
        ws.append([
            ex["record_id"], ex["scenic_area"], platform_of.get(ex["record_id"], ""), ex["title"][:40],
            ex["raw_format"],
            clip(ex["before"][:EXCERPT_LIMIT] + ("…[节选]" if ex["sample_is_excerpt"] else ""), EXCEL_LIMIT),
            clip(ex["after"][:EXCERPT_LIMIT] + ("…[节选]" if ex["sample_is_excerpt"] else ""), EXCEL_LIMIT),
            rules,
        ])
    for col, width in zip("ABCDEFGH", (22, 9, 11, 30, 10, 55, 55, 45)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row[5:7]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # ── Sheet 4: 拒绝记录 ─────────────────────────────────────────
    ws = wb.create_sheet("拒绝记录")
    sheet_header(ws, ["record_id", "景区", "平台", "标题", "拒绝原因", "清洗后非空白字符数", "清洗内容（节选）"])
    for row in rejected:
        ws.append([
            row["record_id"], row["scenic_area"], row["source_platform"], row["title"][:40],
            "；".join(row.get("rejection_reasons", [])),
            row.get("clean_nonspace_char_count", ""),
            clip(row.get("clean_content", "")[:300]),
        ])
    for col, width in zip("ABCDEFG", (22, 9, 11, 34, 34, 12, 50)):
        ws.column_dimensions[col].width = width

    # ── Sheet 5: 清洗规则统计 ─────────────────────────────────────
    ws = wb.create_sheet("清洗规则统计")
    sheet_header(ws, ["清洗规则", "命中次数（全部输入）", "说明"])
    totals = report["cleaning_rule_totals_all_inputs"]
    for rule, count in sorted(totals.items(), key=lambda kv: -kv[1]):
        ws.append([rule, count, RULE_NOTES.get(rule, "")])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 66

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(json.dumps({"output": OUT.as_posix(), "sheets": wb.sheetnames,
                      "dataset_rows": len(rows), "rejected_rows": len(rejected),
                      "example_rows": min(12, len(picked))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
