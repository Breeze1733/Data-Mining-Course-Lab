"""Experiment 4: manual annotation sampling and evaluation.

--sample  Generate a stratified random sample (pronoun_class × scenic_area, seed=42) and print contexts
--fill    Write manual verdicts into annotation_gold.json (GOLD verdicts are embedded in this file; rerun after editing)
--score   Rule-based resolution vs manual annotation: overall/per-class accuracy + confusion examples + charts
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIGS = OUT / "figs"
N_PER_CELL = 10
SEED = 42
# Expansion round: append annotations beyond the existing 120 cases (5 per cell, independent seed, excluding already-annotated cases)
N_PER_CELL_EXPAND = 5
SEED_EXPAND = 43

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


GOLD: dict[int, tuple[str, str, str]] = {
    0: ("镜海", "POI", ""),
    1: ("九寨沟", "景区", "“这里的水”指九寨沟当地（夜宿地）"),
    2: ("酒店的中餐厅", "设施", "“这里都能吃到”指酒店餐厅，非景区"),
    3: ("原始森林", "POI", ""),
    4: ("松潘古城", "POI", "同句“黄龙”干扰；真先行词为前文“松潘古城”（未收录实体）"),
    5: ("磁器口", "景区", "多景点游记，“这里”指重庆磁器口"),
    6: ("乐山大佛景区", "景区", "“这里有13路公交站”指乐山大佛附近；平台主景区标签为九寨沟"),
    7: ("九寨沟", "景区", "“湖在这里被叫做海子”指九寨沟整体；前句“箭竹海”为干扰"),
    8: ("五彩池", "POI", ""),
    9: ("无", "无", "“此处只能省略一万字”指文中省略内容，非地点"),
    10: ("景山公园", "POI", "多景点游记（故宫/景山段）"),
    11: ("南锣鼓巷", "POI", "多景点游记"),
    12: ("全聚德烤鸭店", "设施", "“这里食客等位”指餐厅"),
    13: ("清华大学校园", "景区", "多景点游记（清华段）"),
    14: ("北京大学", "景区", "多景点游记（北大段）"),
    15: ("耕织图", "POI", ""),
    16: ("颐和园", "景区", ""),
    17: ("颐和园", "景区", ""),
    18: ("荷花市场", "POI", "多景点游记（什刹海段）"),
    19: ("金山岭长城", "POI", "多景点游记（长城段）"),
    20: ("西海大峡谷", "POI", "前文以“梦幻景区”代称，该代称未入实体词表"),
    21: ("慈光阁/云谷寺/北大门/西大门", "集合-POI", "入口并列结构，“那里”指多个地点"),
    22: ("黄山", "景区", ""),
    23: ("雲亼民宿", "设施", "“这里的客房”指民宿"),
    24: ("光明顶", "POI", ""),
    25: ("三清山", "景区", "多景区游记（三清山段）"),
    26: ("雲亼民宿", "设施", ""),
    27: ("北海", "POI", "“北海宾馆附近”，归一化到北海可接受"),
    28: ("鳌鱼峰", "POI", ""),
    29: ("西海大峡谷", "POI", ""),
    30: ("五花海", "POI", ""),
    31: ("五彩池", "POI", ""),
    32: ("南门方向岔路", "路线", "“这条路”指前句“一条往南门”的岔道（乐山大佛景区内）"),
    33: ("成都", "景区", "“这座城市”指成都；同句“动车票”干扰"),
    34: ("则查洼沟", "POI", "前句“下一条沟—查洼沟”；文本变体“查洼沟”未入词典"),
    35: ("则查洼沟", "POI", "前文“则渣洼沟”拼写变体未入词典"),
    36: ("进沟山路（G248）", "路线", "指前文山路，非景点"),
    37: ("五彩池", "POI", ""),
    38: ("红原", "景区", "“它的缠绵悱恻”指红原四季；红原未收录"),
    39: ("雅克夏雪山", "POI", ""),
    40: ("圆明园", "POI", "多景点游记（圆明园段）"),
    41: ("石舫", "POI", "同句“长廊”劫持，真先行词为句首主语清晏舫（石舫）"),
    42: ("北海", "POI", "北京北海，多景点游记"),
    43: ("半日精华线", "路线", "指前句路线标题"),
    44: ("北海", "POI", ""),
    45: ("颐和园", "景区", ""),
    46: ("天安门广场", "POI", "多景点游记"),
    47: ("长廊", "POI", ""),
    48: ("佛香阁", "POI", "先行词在代词之后（后置命名“名为佛香阁”）"),
    49: ("颐和园", "景区", ""),
    50: ("太平索道线路", "路线", "指北大门太平索道进出的线路"),
    51: ("往莲花峰的岔路", "路线", "指“往左手那条路”"),
    52: ("祠堂", "其他", "普通名词“祠堂”，非POI"),
    53: ("两日行程路线", "路线", "指本篇所述两日路线"),
    54: ("黄山", "景区", ""),
    55: ("庐山老别墅", "其他", "多景区游记（庐山段）"),
    56: ("黄山", "景区", ""),
    57: ("迎客松", "POI", ""),
    58: ("五步蛇", "其他", "“它的利用价值”指五步蛇"),
    59: ("X063公路", "路线", "指前文沿江公路"),
    60: ("藏餐厅主人一家", "他人", "服务场景中的“他们”，非同行者"),
    61: ("当地人", "他人", "前句“问了当地人”"),
    62: ("同行者", "同行者", "前句“他们”即同行队伍"),
    63: ("无", "无", "诗化指代“这片土地”，无明确实体"),
    64: ("同团迟到的两名游客", "他人", "非作者同行者，是同团其他游客"),
    65: ("同行者（两老母亲）", "同行者", ""),
    66: ("同行者（郭枫）", "同行者", ""),
    67: ("同团迟到的两名游客", "他人", ""),
    68: ("硬石餐厅", "设施", "“他们家招牌”指餐厅店家"),
    69: ("车上导游", "他人", "规则识别为他人，正确"),
    70: ("同行者", "同行者", ""),
    71: ("司机与导游们", "他人", "前文“他的另一个同事”指导游群体"),
    72: ("同行者", "同行者", ""),
    73: ("景区管理者", "他人", "前文“管理者”"),
    74: ("同行者", "同行者", ""),
    75: ("周围的小朋友", "他人", ""),
    76: ("蒙古大军", "他人", "历史叙述"),
    77: ("云川酒店", "设施", "“他们后院”指酒店"),
    78: ("格鲁一家（虚构角色）", "其他", "小黄人项目角色"),
    79: ("同行者", "同行者", ""),
    80: ("同行者（老婆和大老爷）", "同行者", ""),
    81: ("往山坡走的游客", "他人", "前句“见到一些游客”"),
    82: ("黄山酒店", "设施", "“他们的管家服务”指酒店"),
    83: ("光明顶/迎客松等景点", "集合-POI", "人称代词指景点集合，类别跨越 person→POI 集合"),
    84: ("酒店前台", "他人", ""),
    85: ("馄饨店主一家", "他人", ""),
    86: ("隔壁的金华人游客", "他人", ""),
    87: ("上山的游客", "他人", ""),
    88: ("挑山工", "他人", "角色词“挑山工”不在规则词表（词表只有“挑夫”）"),
    89: ("同行者（老外）", "同行者", ""),
    90: ("水上步栈道", "其他", "“穿梭在其中”指栈道与水流之间"),
    91: ("五次重要会议", "集合-其他", "普通名词集合"),
    92: ("窟龛与雕像", "集合-其他", ""),
    93: ("二十余栋景观套房", "集合-其他", ""),
    94: ("扎如寺", "POI", "“寺院标志性建筑”即扎如寺（九寨沟周边）"),
    95: ("两种进酒店方式", "集合-其他", "“两种方式…其中之一原因”"),
    96: ("一行5人家庭", "集合-人", "“其中”指人的集合"),
    97: ("无", "无", "承接行程单，无明确集合实体"),
    98: ("冰川地貌类型", "集合-其他", "前句“悬冰川、冰斗冰川和平顶冰川”"),
    99: ("雪山景色", "其他", "虚化“其中的壮美”"),
    100: ("恭王府", "POI", "“其中”承接王府整体；多景点游记"),
    101: ("圆明园", "POI", ""),
    102: ("圆明园", "POI", ""),
    103: ("三副转轮藏", "集合-其他", "雍和宫/颐和园/智化寺的转轮藏"),
    104: ("718联合厂拆分后的各厂", "集合-其他", ""),
    105: ("明长城各段", "集合-其他", ""),
    106: ("东四胡同群", "集合-其他", ""),
    107: ("南长城敌楼", "集合-其他", ""),
    108: ("国宝展馆", "其他", "虚化“沉寂在其中”"),
    109: ("几位北京大爷", "集合-人", ""),
    110: ("6顿餐", "集合-其他", ""),
    111: ("五个补给站", "集合-其他", "普通名词集合"),
    112: ("宅内陈列", "其他", ""),
    113: ("馆藏品", "集合-其他", ""),
    114: ("月沼", "POI", "“倒映其中”指月沼水体；前句POI劫持"),
    115: ("山间雾景", "其他", "虚化“走在其中”"),
    116: ("72座峰", "集合-其他", "后文列举的三大主峰是子集"),
    117: ("72个山峰", "集合-其他", ""),
    118: ("两种上山方式", "集合-其他", "徒步 vs 索道"),
    119: ("两个环线", "集合-其他", "“8”字两个环行"),
}


EXPAND_GOLD: dict[int, tuple[str, str, str]] = {
    0: ("九寨沟", "景区", "“这里的水”指夜宿地九寨沟当地，同第1例口径"),
    1: ("诺日朗", "POI", "“汇合点在这里”指诺日朗换乘中心"),
    2: ("郎木寺", "景区", "多景点游记（郎木寺段）"),
    3: ("无", "无", "“那边”指附近拍照点，文本无足够线索确定具体位置"),
    4: ("就餐的餐馆", "设施", "“这里的消费”指等位就餐的餐厅"),
    5: ("佛香阁", "POI", "“站在这里”指佛香阁制高点"),
    6: ("颐和园", "景区", "“这里”指园内游人稀少处，属颐和园范围"),
    7: ("紫禁城", "景区", "多景点游记（故宫/紫禁城段）"),
    8: ("避暑山庄", "景区", "多景点游记（承德避暑山庄段）"),
    9: ("三里屯太古里", "景区", "多景点游记（三里屯段），前句明名“北京三里屯太古里”"),
    10: ("云谷寺", "POI", "“到那里时”指车抵达的云谷寺山门"),
    11: ("玉屏楼宾馆", "POI", "景区内酒店，参照第27例（北海宾馆→POI）口径"),
    12: ("泰安", "景区", "多景区游记（泰安/泰山段），“这里”指泰安当地"),
    13: ("山上的大平台", "设施", "文本未给出平台专名，指山上可供饮食与过夜的公共平台"),
    14: ("西海岸景区", "景区", "同句“西海岸景区”，多景区游记（三清山段）"),
    15: ("无", "无", "“其它”为限定词非回指代词，检测误触发"),
    16: ("那群大型飞鸟", "其他", "指前句的飞鸟群，非实体体系内对象"),
    17: ("九寨沟", "景区", "“它的美”指九寨沟美景整体（参照第38例口径）"),
    18: ("无", "无", "“其它海子”为限定结构非回指代词，检测误触发"),
    19: ("黄龙", "景区", "“它”指黄龙（联游景区段）"),
    20: ("长廊", "POI", "先行词为“廊上斑驳的画”，归至长廊实体"),
    21: ("界湖桥", "POI", "“这座桥”承前指界湖桥（清漪园时期名柳桥）"),
    22: ("青芝岫（乐寿堂大石头）", "其他", "“它”指青芝岫巨石，未入实体体系"),
    23: ("紫禁城", "景区", "“这座皇城”指紫禁城，多景点游记（故宫段）"),
    24: ("圆明园残石", "其他", "“它们”指圆明园遗址残石，虚化集体指代"),
    25: ("本次两日徒步路线", "路线", "“这条路线”指本篇所述行程路线"),
    26: ("祠堂", "其他", "“它”承前指祠堂（普通名词）"),
    27: ("黄山温泉", "POI", "“它”承前指黄山温泉"),
    28: ("送客松", "POI", "“记住它”指后置命名的送客松"),
    29: ("黄山", "景区", "“它的美”指黄山（参照第38例口径）"),
    30: ("当地人", "他人", "同句“当地人说”，指当地居民"),
    31: ("沈阳6人老年团队", "他人", "前句“6人老年人团队”，非作者同行者"),
    32: ("图旅影像馆", "设施", "“他们家”指租赁商铺店家"),
    33: ("三个川大男孩", "他人", "前句偶遇的川大学生，非同行者"),
    34: ("同路几个小姑娘", "他人", "前句“遇见…几个小姑娘”，非作者队伍"),
    35: ("同行者", "同行者", "“她们两个”即作者同行家人"),
    36: ("两个胜利者（英法联军）", "他人", "历史叙述，前句“两个胜利者”"),
    37: ("同行者", "同行者", ""),
    38: ("等879路的一队人", "他人", "同句“站了一队人”"),
    39: ("江南官吏", "他人", "同句主语“江南官吏”，历史叙述"),
    40: ("抬滑竿的年轻人", "他人", "同句“抬滑竿的…年轻人”"),
    41: ("望秀山客栈", "设施", "“他们”指望秀山客栈（代订服务方）"),
    42: ("挑山工", "他人", "承前句挑山工重担语境，“对比他们”指挑山工"),
    43: ("挑山工", "他人", "前句“挑山工…挑上来”，问价对象为挑山工"),
    44: ("迎面来的登山者", "他人", "同句“从下面上来的人”"),
    45: ("没有下来的两组人", "集合-人", "“其中”承接前句“两组人”"),
    46: ("岩溶层色调", "其他", "“其中”指岩溶层金黄主色调之中，普通名词"),
    47: ("白石海", "POI", "“倒映其中”指白石海湖面（前句明名），参照第114例口径"),
    48: ("墨海", "POI", "“倒映其中”指墨海湖面（前句明名）"),
    49: ("九寨沟Y形沟域", "其他", "“其中”指Y形沟谷范围，普通指称"),
    50: ("颐和园占地面积", "其他", "“其中”指占地面积整体中的一部分（湖水），普通名词整体-部分"),
    51: ("展馆内的著名国宝", "集合-其他", "“其中”承接国宝列举"),
    52: ("胁侍塑像的图案", "其他", "“其中”指塑像衣纹图案之中"),
    53: ("太和殿/中和殿/保和殿三大殿", "集合-POI", "“其中”承接三大殿枚举"),
    54: ("外八庙十二座寺庙群", "集合-其他", "“其中”承接十二座寺庙（普通名词集合）"),
    55: ("《名松谱》收录的黄山松树", "集合-其他", "“其中”承接松树集合（普通名词）"),
    56: ("费用合计", "其他", "“其中”承接费用总额（账目承接）"),
    57: ("田园画卷（篁岭村景致）", "其他", "虚化“置身其中”，指前述田园景致"),
    58: ("黄山全部景观", "其他", "整体-部分：黄山景观全体中的一部分"),
    59: ("登过的六座山", "集合-其他", "“其中”承接六座山（普通名词集合）"),
}


def load_cases() -> list[dict]:
    return [json.loads(l) for l in (OUT / "pronoun_cases.jsonl").open(encoding="utf-8")]


def sample(cases: list[dict]) -> None:
    cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, c in enumerate(cases):
        cells[(c["pronoun_class"], c["scenic_area"])].append(i)
    rng = random.Random(SEED)
    picks = []
    for cell in sorted(cells):
        pool = cells[cell]
        picks.extend(rng.sample(pool, min(N_PER_CELL, len(pool))))
    out = []
    for i in picks:
        c = cases[i]
        out.append({
            "case_index": i, "pronoun": c["pronoun"], "pronoun_class": c["pronoun_class"],
            "scenic_area": c["scenic_area"], "record_id": c["record_id"], "doc_start": c["doc_start"], "doc_end": c["doc_end"],
            "prev2": c["prev2_sentence"][-60:], "prev": c["prev_sentence"][-70:],
            "sentence": c["sentence"][:120],
            "rule_resolution": c["resolution"], "rule_kind": c["resolution_kind"],
        })
    (OUT / "annotation_sample_dev.json").write_text(
        json.dumps({"seed": SEED, "n_per_cell": N_PER_CELL, "samples": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    for j, s in enumerate(out):
        print(f"{j:2d} [{s['pronoun_class']}/{s['pronoun']}|{s['scenic_area']}] 规则→{s['rule_resolution']}({s['rule_kind']})")
        print(f"    前2: {s['prev2']}")
        print(f"    前1: {s['prev']}")
        print(f"    本句: {s['sentence']}")


def expand_sample(cases: list[dict]) -> None:
    """Expansion sampling: exclude already-annotated cases, then draw N_PER_CELL_EXPAND more per cell (independent seed)."""
    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    annotated = {g["case_index"] for g in gold}
    cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, c in enumerate(cases):
        if i in annotated:
            continue
        cells[(c["pronoun_class"], c["scenic_area"])].append(i)
    rng = random.Random(SEED_EXPAND)
    picks = []
    for cell in sorted(cells):
        picks.extend(rng.sample(cells[cell], min(N_PER_CELL_EXPAND, len(cells[cell]))))
    out = []
    for i in picks:
        c = cases[i]
        out.append({
            "case_index": i, "pronoun": c["pronoun"], "pronoun_class": c["pronoun_class"],
            "scenic_area": c["scenic_area"], "record_id": c["record_id"], "doc_start": c["doc_start"], "doc_end": c["doc_end"],
            "prev2": c["prev2_sentence"][-60:], "prev": c["prev_sentence"][-70:],
            "sentence": c["sentence"][:120],
            "rule_resolution": c["resolution"], "rule_kind": c["resolution_kind"],
        })
    (OUT / "annotation_sample_test.json").write_text(
        json.dumps({"seed": SEED_EXPAND, "n_per_cell": N_PER_CELL_EXPAND, "samples": out},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    for j, s in enumerate(out):
        print(f"{j:2d} [{s['pronoun_class']}/{s['pronoun']}|{s['scenic_area']}] 规则→{s['rule_resolution']}({s['rule_kind']})")
        print(f"    前2: {s['prev2']}")
        print(f"    前1: {s['prev']}")
        print(f"    本句: {s['sentence']}")


def fill(cases: list[dict]) -> None:
    data = json.loads((OUT / "annotation_sample_dev.json").read_text(encoding="utf-8"))
    existing = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    anchors = {g["case_index"]: g for g in existing}
    gold_rows = []
    for j, s in enumerate(data["samples"]):
        if j not in GOLD:
            continue
        case = cases[s["case_index"]]
        anchor = anchors.get(s["case_index"], {})
        if any(anchor.get(k) != case[k] for k in ("record_id", "pronoun", "doc_start", "doc_end")):
            raise ValueError("Cannot reuse indexed labels for a changed sample; annotate it independently")
        ant, kind, note = GOLD[j]
        gold_rows.append({
            "case_index": s["case_index"], "pronoun": s["pronoun"], "pronoun_class": s["pronoun_class"],
            "scenic_area": s["scenic_area"], "record_id": s["record_id"],
            "gold_antecedent": ant, "gold_kind": kind, "note": note,
            "rule_resolution": s["rule_resolution"], "rule_kind": s["rule_kind"],
            "doc_start": case["doc_start"], "doc_end": case["doc_end"],
        })
    (OUT / "annotation_gold.json").write_text(
        json.dumps({"annotated_by": "课程实验（作者本人）", "n": len(gold_rows), "annotations": gold_rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gold written: {len(gold_rows)}")


def fill_expand(cases: list[dict]) -> None:
    """Merge expansion annotations: keep the existing 120 rows untouched (append-only); new rows come from EXPAND_GOLD + the expansion sampling file."""
    data = json.loads((OUT / "annotation_sample_test.json").read_text(encoding="utf-8"))
    gold_doc = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))
    existing = gold_doc["annotations"]
    anchors = {g["case_index"] for g in existing}
    new_rows = []
    for j, s in enumerate(data["samples"]):
        if j not in EXPAND_GOLD:
            continue
        if s["case_index"] in anchors:
            raise ValueError(f"case_index {s['case_index']} already annotated; expansion samples must be disjoint")
        case = cases[s["case_index"]]
        for k in ("record_id", "pronoun", "doc_start", "doc_end"):
            if s[k] != case[k]:
                raise ValueError(f"Expand sample stale at j={j}: {k}")
        ant, kind, note = EXPAND_GOLD[j]
        new_rows.append({
            "case_index": s["case_index"], "pronoun": s["pronoun"], "pronoun_class": s["pronoun_class"],
            "scenic_area": s["scenic_area"], "record_id": s["record_id"],
            "gold_antecedent": ant, "gold_kind": kind, "note": note,
            "rule_resolution": s["rule_resolution"], "rule_kind": s["rule_kind"],
            "doc_start": case["doc_start"], "doc_end": case["doc_end"],
            "split": "test",
        })
    merged = existing + new_rows
    gold_doc["annotations"] = merged
    gold_doc["n"] = len(merged)
    gold_doc["expansion"] = {"seed": SEED_EXPAND, "n_per_cell": N_PER_CELL_EXPAND, "n_added": len(new_rows)}
    (OUT / "annotation_gold.json").write_text(
        json.dumps(gold_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gold expanded: +{len(new_rows)} -> {len(merged)}")


def doc_grouped_split(gold_rows: list[dict], target_test: int = 60) -> dict:
    """Doc-grouped dev/test split — sentence-level random splits leak within-document info (the two original rounds share 25 documents).

    Deterministic: sort the document list, shuffle with rng(42), assign whole documents to test until the sample quota is met, the rest go to dev.
    Near-duplicate constraint: near-duplicate pairs are forced to the same side (A05 fix — 2 pairs previously leaked across splits).
    Returns {record_id: "dev"|"test"}.
    """
    import random
    doc_ids = sorted({g["record_id"] for g in gold_rows})
    rng = random.Random(42)
    rng.shuffle(doc_ids)
    sizes = {d: sum(1 for g in gold_rows if g["record_id"] == d) for d in doc_ids}
    # A05: near-duplicate pairs -> transitive-closure grouping -> one side per group
    quality_path = ROOT.parent / "task1/data/processed/quality_report.json"
    near_dup_groups = []
    if quality_path.exists():
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        for _d in quality.get("near_duplicate_pairs", []):
            _a, _b = _d["record_id_a"], _d["record_id_b"]
            for _grp in near_dup_groups:
                if _a in _grp or _b in _grp:
                    _grp.add(_b)
                    _grp.add(_a)
                    break
            else:
                near_dup_groups.append({_a, _b})
    rec2grp = {}
    for _gi, _grp in enumerate(near_dup_groups):
        for _r in _grp:
            rec2grp[_r] = _gi
    # Split by group rather than by document (the first document of a group encountered decides the whole group's side)
    assigned = set()
    split, n_test = {}, 0
    for d in doc_ids:
        if d in assigned:
            continue
        grp = near_dup_groups[rec2grp[d]] if d in rec2grp else {d}
        target = "test" if n_test < target_test else "dev"
        for member in sorted(grp):
            if member in sizes:
                split[member] = target
                assigned.add(member)
                if target == "test":
                    n_test += sizes[member]
    return split


sys.path.insert(0, str(ROOT.parent))
from common.fingerprints import data_fingerprints as _data_fingerprints


def wilson_ci(k: int, n: int, z: float = 1.96) -> dict:
    """Wilson 95% confidence interval (robust interval for small-sample proportions)."""
    if n == 0:
        return {"lo": None, "hi": None}
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    spread = (z / denom) * (p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5
    return {"lo": round(max(0.0, center - spread), 3), "hi": round(min(1.0, center + spread), 3)}


def score(cases: list[dict]) -> None:
    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    FIGS.mkdir(parents=True, exist_ok=True)
    rows = []
    for g in gold:
        case = cases[g["case_index"]]
        for field in ("record_id", "pronoun", "doc_start", "doc_end"):
            if field not in g or case[field] != g[field]:
                raise ValueError(f"Stale coreference annotation at {g['case_index']}: {field}; re-align the gold set before scoring")
        pred, truth = case["resolution"], g["gold_antecedent"]
        # Correctness: kind must match and identity must match (person/set/none compared by their special kinds; scenic-name fallback counts as “POI/景区” granularity)
        # Add the "其他" mapping — single-noun antecedents (non-entity concepts) are judged "其他" per the gold lineage, distinguished from "名词集合" (multi-element sets)
        canon = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
                 "名词集合": "集合-其他", "其他": "其他", "前文POI集合": "集合-POI", "人称集合": "集合-人", "路线": "路线", "设施": "设施", "无明确先行词": "无"}
        kind_match = canon.get(case["resolution_kind"]) == g["gold_kind"]
        if g["gold_kind"] in ("POI", "景区"):
            name_match = pred == truth or (case["resolution_kind"] == "景区名" and truth == case["scenic_area"])
        else:
            name_match = True
        rows.append({**g, "correct": bool(kind_match and name_match),
                     "kind_match": bool(kind_match), "name_match": bool(name_match),
                     "cur_pred": pred, "cur_kind": case["resolution_kind"],
                     "cur_evidence": case.get("evidence", "")})
    acc_overall = sum(r["correct"] for r in rows) / len(rows)
    by_class = defaultdict(lambda: [0, 0])
    for r in rows:
        by_class[r["pronoun_class"]][1] += 1
        by_class[r["pronoun_class"]][0] += r["correct"]
    # Split metric (doc-grouped): whole documents go into dev/test, eliminating within-document leakage
    doc_split = doc_grouped_split(gold)
    by_split = defaultdict(lambda: [0, 0])
    for r in rows:
        sp = doc_split[r["record_id"]]
        by_split[sp][1] += 1
        by_split[sp][0] += r["correct"]
    # D04: abstention metric — "无明确先行词" is an interpretable abstention; coverage and accuracy are reported separately
    by_scenic_acc = defaultdict(lambda: [0, 0])
    by_platform_acc = defaultdict(lambda: [0, 0])
    for r in rows:
        by_scenic_acc[r["scenic_area"]][1] += 1
        by_scenic_acc[r["scenic_area"]][0] += r["correct"]
        by_platform_acc[r.get("source_platform") or r["record_id"].split("_")[0]][1] += 1
        by_platform_acc[r.get("source_platform") or r["record_id"].split("_")[0]][0] += r["correct"]
    abstain_by_class = defaultdict(lambda: [0, 0])
    for r in rows:
        abstain_by_class[r["pronoun_class"]][1] += 1
        abstain_by_class[r["pronoun_class"]][0] += (r["cur_pred"] == "NONE")
    abstain_overall = [sum(v[0] for v in abstain_by_class.values()), len(rows)]
    result = {
        "n": len(rows),
        "accuracy_overall": round(acc_overall, 3),
        "abstention": {
            "note": "弃权=解析为 NONE（可解释的不定位）；覆盖率=1−弃权率，与准确率分开解读",
            "overall": {"n": abstain_overall[1],
                        "abstained": abstain_overall[0],
                        "coverage": round(1 - abstain_overall[0] / max(1, abstain_overall[1]), 3)},
            "by_class": {k: {"n": v[1], "abstained": v[0],
                             "coverage": round(1 - v[0] / max(1, v[1]), 3)}
                         for k, v in sorted(abstain_by_class.items())},
        },
        "accuracy_by_class": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(by_class.items())},
        "accuracy_by_split": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(by_split.items())},
        "accuracy_by_scenic": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3),
                                   "ci95": wilson_ci(v[0], v[1])}
                               for k, v in sorted(by_scenic_acc.items())},
        # Stratified by platform (XHS vs 携程), with CI
        "accuracy_by_platform": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3),
                                     "ci95": wilson_ci(v[0], v[1])}
                                 for k, v in sorted(by_platform_acc.items())},
        "errors_by_split": {k: v[1] - v[0] for k, v in sorted(by_split.items())},
        "split_method": "文档分组：整文档划入 dev/test（rng42 确定性），无同文档泄漏",
        # Error list cites the current predictions (historical rule_resolution snapshots remain only in the gold file for reference)
        "errors": [
            {"pronoun": r["pronoun"], "class": r["pronoun_class"], "scenic": r["scenic_area"],
             "pred": r["cur_pred"], "pred_kind": r["cur_kind"], "evidence": r["cur_evidence"],
             "gold": r["gold_antecedent"], "gold_kind": r["gold_kind"], "note": r["note"]}
            for r in rows if not r["correct"]],
        # Kind metrics and antecedent-identity metrics are reported separately — non-entity kinds are judged on kind only, never counted as identity-correct
        "kind_only_accuracy": round(sum(r["kind_match"] for r in rows) / len(rows), 3) if rows else None,
        # D07: auxiliary "specific member hit" metric for set kinds — counted when the resolved name contains one of the gold set members,
        # read separately from the coarse kind accuracy (distinguishing "kind-correct" from "member-correct")
        "set_member_hit": None,
        "accuracy_ci95": wilson_ci(round(acc_overall * len(rows)), len(rows)),
        "data_fingerprints": _data_fingerprints(),
        "identity_ci95": wilson_ci(
            sum(1 for r in rows if r["gold_kind"] in ("POI", "景区") and r["correct"]),
            sum(1 for r in rows if r["gold_kind"] in ("POI", "景区"))),
        "identity_scope": {
            "n_identity_checked": sum(1 for r in rows if r["gold_kind"] in ("POI", "景区")),
            "identity_accuracy": round(
                sum(1 for r in rows if r["gold_kind"] in ("POI", "景区") and r["correct"])
                / max(1, sum(1 for r in rows if r["gold_kind"] in ("POI", "景区"))), 3),
        },
    }
    set_rows = [r for r in rows if r["gold_kind"].startswith("集合") or r["pronoun_class"] == "set"]
    member_hits = 0
    member_detail = []
    for r in set_rows:
        gold_members = [m for m in re.split(r"[、/／,，;；]|和|与", r["gold_antecedent"]) if len(m) >= 2]
        hit = any((m in r["cur_pred"]) or (r["cur_pred"] in m) for m in gold_members
                  if m not in ("无",)) if gold_members else False
        member_hits += hit
        member_detail.append({"pronoun": r["pronoun"], "gold": r["gold_antecedent"],
                              "pred": r["cur_pred"], "member_hit": hit})
    result["set_member_hit"] = {
        "n_set_cases": len(set_rows), "member_hits": member_hits,
        "member_hit_rate": round(member_hits / max(1, len(set_rows)), 3),
        "detail": member_detail,
    }
    (OUT / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # Charts: per-class accuracy + pronoun distribution
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150)
    cls = sorted(by_class)
    accs = [by_class[c][0] / by_class[c][1] for c in cls]
    ns = [by_class[c][1] for c in cls]
    bars = axes[0].bar(cls, accs, 0.5, color="#1565C0", alpha=0.85)
    for b, n in zip(bars, ns):
        axes[0].text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"n={n}", ha="center", fontsize=9)
    axes[0].set_ylim(0, 1.1)
    axes[0].set_title("规则消解准确率（按代词类别）")
    axes[0].spines[["top", "right"]].set_visible(False)
    pron_counter = Counter(g["pronoun"] for g in gold)
    axes[1].bar(list(pron_counter), list(pron_counter.values()), 0.6, color="#2E7D32", alpha=0.85)
    axes[1].set_title("标注样本的代词分布")
    axes[1].spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "coref_evaluation.png")
    plt.close(fig)
    print(json.dumps({k: result[k] for k in ("n", "accuracy_overall", "accuracy_by_class")}, ensure_ascii=False, indent=1))
    print("errors:", len(result["errors"]))
    for e in result["errors"][:15]:
        print(" ", e)


def run_propagation() -> int:
    gold = json.loads((OUT / "annotation_gold.json").read_text(encoding="utf-8"))["annotations"]
    cases = load_cases()
    split = doc_grouped_split(gold)
    CANON = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
             "名词集合": "集合-其他", "其他": "其他", "前文POI集合": "集合-POI", "人称集合": "集合-人",
             "路线": "路线", "设施": "设施", "无明确先行词": "无"}

    # Per-record entity pools: POI/transport entity counts (from the current entities_refined)
    pools = {}
    rec_type = {}
    ents_by_rec = {}
    with (ROOT.parent / "task2/output/exp2/entities_refined.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            pools[r["record_id"]] = (
                sum(1 for e in r["entities"] if e["type"] == "景点POI"),
                sum(1 for e in r["entities"] if e["type"] == "交通方式"))
            ents_by_rec[r["record_id"]] = r["entities"]
    with (ROOT.parent / "task1/data/processed/dataset_clean.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rec_type[r["record_id"]] = r.get("text_type", "?")

    rows = []
    for g in gold:
        if split[g["record_id"]] != "dev":
            continue
        c = cases[g["case_index"]]
        km = CANON.get(c["resolution_kind"]) == g["gold_kind"]
        if g["gold_kind"] in ("POI", "景区"):
            nm = c["resolution"] == g["gold_antecedent"] or (c["resolution_kind"] == "景区名" and g["gold_antecedent"] == c["scenic_area"])
        else:
            nm = True
        n_poi, n_tra = pools.get(c["record_id"], (0, 0))
        # Stratification instead uses mechanical dimensions with variance: same-sentence distractor count, pronoun-to-nearest-entity distance
        _ents = ents_by_rec.get(c["record_id"], [])
        _ds, _de = c["doc_start"], c["doc_end"]
        _sent_lo, _sent_hi = c["doc_start"] - len(c["prev_sentence"]), c["doc_end"] + 10 ** 9
        _in_sent = [e for e in _ents
                    if e["type"] in ("景点POI", "交通方式")
                    and e["start"] < _ds and e["end"] > _ds - (c["sentence"].find(c["pronoun"]) if c["pronoun"] in c["sentence"] else 0)]
        _distr = sum(1 for e in _ents
                     if e["type"] in ("景点POI", "交通方式")
                     and _sent_lo <= e["start"] < _ds)
        before = [e for e in _ents if e["end"] <= _ds and e["type"] in ("景点POI", "交通方式")]
        _dist = (_ds - max(e["end"] for e in before)) if before else None
        rows.append({"correct": bool(km and nm), "n_poi": n_poi, "n_tra": n_tra,
                     "distractors": _distr, "dist": _dist,
                     "text_type": rec_type.get(c["record_id"], "?"),
                     "pronoun_class": c["pronoun_class"]})

    def layer(keyfn, name):
        buckets = defaultdict(lambda: [0, 0])
        for r in rows:
            k = keyfn(r)
            buckets[k][1] += 1
            buckets[k][0] += r["correct"]
        return {"layer": name,
                "buckets": {str(k): {"n": v[1], "accuracy": round(v[0] / v[1], 3) if v[1] else None,
                                     "ci95": wilson_ci(v[0], v[1])}
                            for k, v in sorted(buckets.items(), key=lambda kv: str(kv[0]))}}

    report = {
        "title": "/ 扩展：消解难度分层与传播假设检验（dev 120 例）",
        "method": "传播假设（词典缺口→消解失败）在本样本不可检验：人工标注评测集按实体丰富游记构造，"
                  "120 例记录级 POI 池全部 ≥8（无方差）。改按机械难度维度分层："
                  "代词前同句干扰实体数、代词-最近前文实体距离。真实信号：最近实体 ≤20 字符层 "
                  "acc 显著高于更远层——错误集中在实体池启发式支撑薄弱的位置（真实先行词多为非实体"
                  "名词或跨句远距），与 的名词回退改进方向一致。仅 dev 侧，Wilson 95% CI。",
        "overall": {"n": len(rows),
                    "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3)},
        "layers": [
            layer(lambda r: str(min(r["distractors"], 3)), "代词前同句干扰实体数（封顶3）"),
            layer(lambda r: "0-20" if r["dist"] is not None and r["dist"] <= 20
                  else "21-60" if r["dist"] is not None and r["dist"] <= 60
                  else "61+" if r["dist"] is not None else "无前文实体",
                  "代词-最近前文实体距离（字符）"),
            layer(lambda r: r["pronoun_class"], "代词语义类别"),
        ],
    }
    report["layers"] = [x for x in report["layers"] if x]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "error_propagation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for l in report["layers"]:
        print(f"[{l['layer']}]")
        for k, v in l["buckets"].items():
            print(f"  {k:12s} n={v['n']:3d} acc={v['accuracy']} CI={v['ci95']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--fill", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--expand-sample", action="store_true",
                        help="扩容抽样：排除已标注 case，每格再抽 N_PER_CELL_EXPAND 例")
    parser.add_argument("--propagation", action="store_true",
                        help="错误传播/难度分层分析（H07/H08 口径，输出 metrics/error_propagation.json）")
    parser.add_argument("--fill-expand", action="store_true",
                        help="把 EXPAND_GOLD 判定追加合并进 annotation_gold.json（既有行不动）")
    args = parser.parse_args()
    cases = load_cases()
    if args.sample:
        sample(cases)
    elif args.fill:
        fill(cases)
    elif args.score:
        score(cases)
    elif args.expand_sample:
        expand_sample(cases)
    elif args.propagation:
        sys.exit(run_propagation())
    elif args.fill_expand:
        fill_expand(cases)
