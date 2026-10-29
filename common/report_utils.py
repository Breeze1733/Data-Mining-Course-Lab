"""课程报告 docx 生成工具：统一的版式（宋体正文/黑体标题/1.3倍行距/首行缩进2字符）。

供各实验报告脚本复用：
    from report_utils import ReportBuilder
    rb = ReportBuilder("《数据挖掘》探索性实验报告", "—实验项目1 景区指南数据采集与预处理")
    rb.section("一、实验目的与任务")
    rb.p("正文段落…")
    rb.table(["列1", "列2"], [[...], [...]], widths=[...])
    rb.save("report.docx")
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
LATIN_FONT = "Times New Roman"


def _set_font(run, cn=BODY_FONT, size=12, bold=False, color=None):
    run.font.name = LATIN_FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), cn)


class ReportBuilder:
    def __init__(self, title: str, subtitle: str):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        self.doc = Document()
        # A4，常规页边距
        for attr, val in (("top_margin", Cm(2.54)), ("bottom_margin", Cm(2.54)),
                          ("left_margin", Cm(3.0)), ("right_margin", Cm(3.0))):
            setattr(self.doc.sections[0], attr, val)
        self._style_defaults()
        t = self.doc.add_paragraph()
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        t.paragraph_format.space_before = Pt(6)
        t.paragraph_format.space_after = Pt(6)
        _set_font(t.add_run(title), cn=HEAD_FONT, size=22, bold=True)
        s = self.doc.add_paragraph()
        s.alignment = WD_ALIGN_PARAGRAPH.CENTER
        s.paragraph_format.space_after = Pt(18)
        _set_font(s.add_run(subtitle), cn=HEAD_FONT, size=16, bold=True)
        self._footer_page_number()

    def _style_defaults(self):
        normal = self.doc.styles["Normal"]
        normal.font.name = LATIN_FONT
        normal.font.size = Pt(12)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
        h1 = self.doc.styles["Heading 1"]
        h1.font.name = LATIN_FONT
        h1.font.size = Pt(14)
        h1.font.bold = True
        h1.font.color.rgb = RGBColor(0, 0, 0)
        h1.element.get_or_add_rPr()
        rf = h1.element.rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            h1.element.rPr.append(rf)
        rf.set(qn("w:eastAsia"), HEAD_FONT)

    def _footer_page_number(self):
        footer = self.doc.sections[0].footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        for tag, attr in (("w:fldChar", {"w:fldCharType": "begin"}),
                          ("w:instrText", None),
                          ("w:fldChar", {"w:fldCharType": "end"})):
            el = OxmlElement(tag)
            if tag == "w:instrText":
                el.set(qn("xml:space"), "preserve")
                el.text = "PAGE \\* MERGEFORMAT"
            else:
                for k, v in attr.items():
                    el.set(qn(k), v)
            run._element.append(el)
        _set_font(run, size=9)

    def section(self, text: str):
        h = self.doc.add_heading(level=1)
        _set_font(h.add_run(text), cn=HEAD_FONT, size=14, bold=True)
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)
        h.paragraph_format.line_spacing = 1.3

    def sub(self, text: str):
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.3
        _set_font(p.add_run(text), cn=HEAD_FONT, size=12, bold=True)

    def p(self, text: str, indent=True, bold=False):
        para = self.doc.add_paragraph()
        pf = para.paragraph_format
        pf.line_spacing = 1.3
        pf.space_after = Pt(3)
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if indent:
            pf.first_line_indent = Pt(24)  # 小四 2 字符
        _set_font(para.add_run(text), size=12, bold=bold)
        return para

    def bullets(self, items: list[str]):
        for item in items:
            p = self.p(item, indent=False)
            p.paragraph_format.left_indent = Pt(24)
            p.paragraph_format.first_line_indent = Pt(0)

    def caption(self, text: str):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(6)
        _set_font(p.add_run(text), size=10.5, bold=True)

    def image(self, path: str | Path, width_cm: float = 14.5):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(path), width=Cm(width_cm))

    def table(self, headers: list[str], rows: list[list], widths: list[float] | None = None,
              font_size: float = 10.5):
        # 学术三线表：顶线/底线 1.5pt，表头下线 0.75pt，无竖线与内横线
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_pr = table._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge, sz in (("top", 12), ("bottom", 12)):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(sz))
            el.set(qn("w:color"), "000000")
            borders.append(el)
        for edge in ("left", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "none")
            borders.append(el)
        tbl_pr.append(borders)
        margins = OxmlElement("w:tblCellMar")
        for side, w in (("top", 40), ("bottom", 40), ("start", 80), ("end", 80)):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), str(w))
            el.set(qn("w:type"), "dxa")
            margins.append(el)
        tbl_pr.append(margins)
        for i, h in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = ""
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_font(para.add_run(h), size=font_size, bold=True)
            tc_borders = OxmlElement("w:tcBorders")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:color"), "000000")
            tc_borders.append(bottom)
            cell._tc.get_or_add_tcPr().append(tc_borders)
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        tbl_header = OxmlElement("w:tblHeader")
        tr_pr.append(tbl_header)
        for row in rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cell = cells[i]
                cell.text = ""
                para = cell.paragraphs[0]
                para.paragraph_format.line_spacing = 1.15
                text = "" if val is None else str(val)
                if "\n" in text:
                    parts = text.split("\n")
                    _set_font(para.add_run(parts[0]), size=font_size)
                    for extra in parts[1:]:
                        para = cell.add_paragraph()
                        para.paragraph_format.line_spacing = 1.15
                        _set_font(para.add_run(extra), size=font_size)
                else:
                    _set_font(para.add_run(text), size=font_size)
        if widths:
            for i, w in enumerate(widths):
                for row in table.rows:
                    row.cells[i].width = Cm(w)
        return table

    def save(self, path: str | Path):
        self.doc.save(path)
        print(f"saved: {path}")
