# -*- coding: utf-8 -*-
"""六类官方路线格式的构造性反例探针（parse_routes 鲁棒性检验）。

对 classify_format 支持的 6 类格式各构造易错变体（真实语料同构、非冻结样本），
直接喂 RouteParser.parse，断言关键解析行为：
- arrow_chain：破折号链中的时间范围（"8:00-10:00"）不被路线分隔符拆开（§5 ）
- numbered_stops：第一站/第二站 汉字编号 + 冒号站点
- numbered_list：阿拉伯数字编号 + 顿号
- kv_route_line：活动路线：键值字段
- prose：由…至… / 先…再… 叙述句
- theme_prose：无序主题段（ordered_route=False）
输出 task3/output/format_probes.json；任一断言失败退出码 1（驱动修复）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "task2/src"))
sys.path.insert(0, str(ROOT / "src"))
if getattr(sys.stdout, "encoding", "") != "utf-8" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from entity_rules import DictMatcher, refined_dictionary  # noqa: E402
from parse_routes import RouteParser  # noqa: E402

OUT = ROOT / "output"

PROBES = [
    {"id": "A1_箭头链_时段标记", "scenic_area": "九寨沟", "ordered_route": True,
     "raw_content": "【上午】长椅准备就绪后游览箭竹海→熊猫海→【中午】诺日朗中心用餐→【下午】五花海→珍珠滩",
     "expect": {"format": "arrow_chain",
                # 诺日朗中心 canonical=诺日朗（词典归一化规则，与图谱一致）
                "pois_in_order": ["箭竹海", "熊猫海", "诺日朗", "五花海", "珍珠滩"]}},

    {"id": "A2_破折号链_时间范围", "scenic_area": "黄山", "ordered_route": True,
     "raw_content": "云谷寺索道（8:00-10:00 排队）—白鹅岭—光明顶—西海大峡谷",
     "expect": {"format": "arrow_chain",
                "pois_in_order": ["云谷寺", "白鹅岭", "光明顶", "西海大峡谷"],
                "time_range_intact": "8:00-10:00"}},
    {"id": "S1_汉字编号站点", "scenic_area": "颐和园", "ordered_route": True,
     "raw_content": "第一站：东宫门\n第二站：仁寿殿\n第三站：昆明湖\n第四站：十七孔桥",
     "expect": {"format": "numbered_stops",
                "pois_in_order": ["东宫门", "仁寿殿", "昆明湖", "十七孔桥"]}},
    {"id": "N1_数字编号列表", "scenic_area": "九寨沟", "ordered_route": True,
     "raw_content": "1、树正群海\n2、犀牛海\n3、镜海\n4、长海",
     "expect": {"format": "numbered_list",
                "pois_in_order": ["树正群海", "犀牛海", "镜海", "长海"]}},
    {"id": "K1_键值路线行", "scenic_area": "九寨沟", "ordered_route": True,
     "raw_content": "活动路线：沟口乘车→原始森林（徒步栈道）→芳草海（返程）",
     "expect": {"format": "kv_route_line",
                "pois_in_order": ["沟口", "原始森林", "芳草海"]}},
    {"id": "P1_散文由至句", "scenic_area": "黄山", "ordered_route": True,
     "raw_content": "清晨由慈光阁出发，经玉屏楼至迎客松，再翻鳌鱼峰抵达光明顶。",
     "expect": {"format": "prose",
                "pois_in_order": ["慈光阁", "玉屏楼", "迎客松", "鳌鱼峰", "光明顶"]}},
    {"id": "T1_主题无序段", "scenic_area": "九寨沟", "ordered_route": False,
     "raw_content": "生态主题：原始森林与天鹅海适合观察鸟类。季节主题：秋季五花海色彩最盛。",
     "expect": {"format": "theme_prose"}},
    {"id": "M1_链内天标记", "route_id": "PROBE-M1", "scenic_area": "九寨沟", "ordered_route": True,
     "raw_content": "【第一天】沟口→诺日朗→【第二天】长海→五彩池",
     "expect": {"pois_days": [("沟口", 1), ("诺日朗", 1), ("长海", 2), ("五彩池", 2)]}},
    {"id": "M3_跨日时段重置", "route_id": "PROBE-M3", "scenic_area": "黄山", "ordered_route": True,
     "raw_content": "【第一天·晚上】住宿白云宾馆→【第二天】光明顶看日出",
     "expect": {"pois_days_periods": [("白云宾馆", 1, "晚上"), ("光明顶", 2, None)],
                "note": "复合标记解析 + 次日第一站不继承前一日晚上"}},
    {"id": "C4_时间范围冒号变体", "scenic_area": "黄山", "ordered_route": True,
     "raw_content": "玉屏楼（6:30～9:30 看日出人流）—鳌鱼峰—天海—光明顶",
     "expect": {"format": "arrow_chain",
                "pois_in_order": ["玉屏楼", "鳌鱼峰", "天海", "光明顶"],
                "time_range_intact": "6:30～9:30"}},
]


def main() -> int:
    entries, stopwords, _ = refined_dictionary()
    parser = RouteParser(DictMatcher(entries, stopwords))
    rows, n_fail = [], 0
    for probe in PROBES:
        route_in = {**probe, "route_id": f'PROBE-{probe["id"]}', "title": "格式探针",
                    "source_record_id": "PROBE", "source_url": "probe://local",
                    "scenic_area": probe["scenic_area"],
                    "ordered_route": probe["ordered_route"], "raw_content": probe["raw_content"]}
        p = parser.parse(route_in)
        steps = p.get("steps", [])
        got_pois = []
        for st in steps:
            got_pois.extend(x["normalized"] for x in st["pois"])
        problems = []
        exp = probe["expect"]
        if "format" in exp and p.get("format") != exp["format"]:
            problems.append(f"format={p.get('format')} 期望 {exp['format']}")
        if "pois_in_order" in exp:
            if got_pois != exp["pois_in_order"]:
                problems.append(f"pois={got_pois} 期望 {exp['pois_in_order']}")
        if "pois_days" in exp:
            got_days = []
            for st in steps:
                got_days.extend((x["normalized"], st["day"]) for x in st["pois"])
            if got_days != exp["pois_days"]:
                problems.append(f"days={got_days} 期望 {exp['pois_days']}")
        if "pois_days_periods" in exp:
            got_dp = []
            for st in steps:
                got_dp.extend((x["normalized"], st["day"], st["period"]) for x in st["pois"])
            if got_dp != exp["pois_days_periods"]:
                problems.append(f"day/period={got_dp} 期望 {exp['pois_days_periods']}")
        if "time_range_intact" in exp:
            raw = probe["raw_content"]
            kept = any(exp["time_range_intact"] in (json.dumps(st, ensure_ascii=False)) for st in steps)
            if not kept:
                problems.append(f"时间范围 {exp['time_range_intact']} 被路线分隔符拆散")
        passed = not problems
        n_fail += 0 if passed else 1
        rows.append({"id": probe["id"], "format": p.get("format"), "pois": got_pois,
                     "n_steps": len(steps), "passed": passed, "problems": problems})
        print(f'{"PASS" if passed else "FAIL"} {probe["id"]} format={p.get("format")} pois={got_pois}'
              + (f" 问题={problems}" if problems else ""))
    report = {
        "title": "六类官方路线格式构造性反例探针（parse_routes 鲁棒性）",
        "method": "6 类格式各构造易错变体直接喂 RouteParser.parse，断言格式识别/POI 序列/时间范围完整性",
        "n_probes": len(PROBES), "n_fail": n_fail, "results": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "format_probes.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n_probes": len(PROBES), "n_fail": n_fail}, ensure_ascii=False))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
