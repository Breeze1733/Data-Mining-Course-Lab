"""实验4：人工标注抽样与评估。

--sample  生成分层随机样本（pronoun_class × scenic_area，seed=42），打印上下文
--fill    把人工判定写入 annotation_gold.json（GOLD 判定内嵌本文件，修改后重跑）
--score   规则消解 vs 人工标注：总体/分类别准确率 + 混淆样例 + 图
"""
from __future__ import annotations

import argparse
import json
import random
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

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# ── 人工判定（--sample 打印上下文后逐条复核填写：key = 序号，value = (antecedent, kind, note)）──
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
    (OUT / "annotation_sample.json").write_text(
        json.dumps({"seed": SEED, "n_per_cell": N_PER_CELL, "samples": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    for j, s in enumerate(out):
        print(f"{j:2d} [{s['pronoun_class']}/{s['pronoun']}|{s['scenic_area']}] 规则→{s['rule_resolution']}({s['rule_kind']})")
        print(f"    前2: {s['prev2']}")
        print(f"    前1: {s['prev']}")
        print(f"    本句: {s['sentence']}")


def fill(cases: list[dict]) -> None:
    data = json.loads((OUT / "annotation_sample.json").read_text(encoding="utf-8"))
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
        # 判定对错：类别一致且指称一致（人称/集合/无先行词按特殊类比较；景区名回退算“POI/景区”粒度）
        canon = {"POI": "POI", "交通": "交通", "景区名": "景区", "他人": "他人", "同行者": "同行者",
                 "名词集合": "集合-其他", "前文POI集合": "集合-POI", "人称集合": "集合-人", "路线": "路线", "无明确先行词": "无"}
        kind_match = canon.get(case["resolution_kind"]) == g["gold_kind"]
        if g["gold_kind"] in ("POI", "景区"):
            name_match = pred == truth or (case["resolution_kind"] == "景区名" and truth == case["scenic_area"])
        else:
            name_match = True
        rows.append({**g, "correct": bool(kind_match and name_match)})
    acc_overall = sum(r["correct"] for r in rows) / len(rows)
    by_class = defaultdict(lambda: [0, 0])
    for r in rows:
        by_class[r["pronoun_class"]][1] += 1
        by_class[r["pronoun_class"]][0] += r["correct"]
    result = {
        "n": len(rows),
        "accuracy_overall": round(acc_overall, 3),
        "accuracy_by_class": {k: {"n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(by_class.items())},
        "errors": [
            {"pronoun": r["pronoun"], "class": r["pronoun_class"], "scenic": r["scenic_area"],
             "rule": r["rule_resolution"], "rule_kind": r["rule_kind"],
             "gold": r["gold_antecedent"], "gold_kind": r["gold_kind"], "note": r["note"]}
            for r in rows if not r["correct"]],
    }
    (OUT / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # 图：分类别准确率 + 代词分布
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--fill", action="store_true")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    cases = load_cases()
    if args.sample:
        sample(cases)
    elif args.fill:
        fill(cases)
    elif args.score:
        score(cases)
