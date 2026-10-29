"""实验5：条件-建议对的人工抽检与可视化。

--sample  分层抽样（pattern × scenic_area，seed=42）打印上下文
--fill    写入人工判定（GOLD 内嵌本文件）
--score   计算抽检正确率/误抽漏抽分类
--charts  条件类型 × 景区柱状图、人群细分图
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
N_PER_CELL = 5
SEED = 42

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# 人工判定：key=(pattern, scenic, 条件归一, 建议归一) → (verdict, note)
def _norm(s: str) -> str:
    import re as _re
    return _re.sub(r"[\s，,。；;、！？!?（）()【】\[\]]+", "", s)


VERDICTS: dict[tuple, tuple[str, str]] = {
    ('P1_显式条件', '九寨沟', '你不是特殊人群', '比如儿童老年人残疾人等其他特殊职业'): ("boundary", "条件列举被并入建议，真建议在“那么”后"),
    ('P1_显式条件', '九寨沟', '生活有开关', '家人们和睦相聚就是以键快乐'): ("wrong", "诗化句子，非游览建议"),
    ('P1_显式条件', '九寨沟', '细细品味', '最好是两天阳光下的九寨会更美'): ("correct", ""),
    ('P1_显式条件', '九寨沟', '你的旅途里有佳人作伴', '那就权当再议'): ("wrong", "“若日朗”（诺日朗错拼）仍命中“若”"),
    ('P1_显式条件', '九寨沟', '包车的话会直接送到索道检票口', '一定要提前几天订'): ("boundary", "跨括号边界：建议抓到括号外价格文本"),
    ('P1_显式条件', '颐和园', '刷身份证就能入园', '比较方便'): ("boundary", "结构成立但建议部分是评价性评论"),
    ('P1_显式条件', '颐和园', '是晚上', '景色会更美'): ("correct", ""),
    ('P1_显式条件', '颐和园', '体力一般或者不想走太多', '中间“乘船过湖”这一步其实很值得保留既省体力也能看到比较完整的湖景视角'): ("correct", ""),
    ('P1_显式条件', '颐和园', '因为这边比八达岭人少', '10月中旬—11月初盛红期'): ("wrong", "建议部分为花期信息陈述，条件与建议错位"),
    ('P1_显式条件', '颐和园', '说颐和园与恭亲王府是文化古迹与古典园林的展现', '天坛公园给我最大的感触对天地的敬畏对自然的敬畏即便是科技发达的现在'): ("wrong", "“如果说”为修辞开头"),
    ('P1_显式条件', '黄山', '出售商品的地方', '展品主要在二楼'): ("wrong", "长句杂糅，建议为事实陈述"),
    ('P1_显式条件', '黄山', '一日游就必须放弃了北海景区天海景区', '就是莲花峰天都峰迎客松都来不及去'): ("boundary", "条件→后果的权衡信息，非动作建议"),
    ('P1_显式条件', '黄山', '全程全靠自己爬上爬下', '把大部分景点都玩一遍至少需要2-3天时间'): ("correct", ""),
    ('P1_显式条件', '黄山', '不上莲花峰', '建议早点下山因为旅行团还没杀到途中美景可任你拍坐索道下山不用人挤人省去和大部队一'): ("correct", "建议带原因从句尾巴"),
    ('P1_显式条件', '黄山', '在油菜花开的季节', '这里是欣赏梯田花海的绝佳之地'): ("correct", ""),
    ('P4_建议推断', '九寨沟', '一般建议', '可以根据当年代表村庄的献祭日期来安排行程时间要注意的是尽管各个村庄的六月会日程网'): ("correct", ""),
    ('P4_建议推断', '九寨沟', '时间条件句内', '尽量早点进景区所以我们就约了7点出发'): ("boundary", "条件“时间（句内）”弱关联"),
    ('P4_建议推断', '九寨沟', '一般建议', '走左边不绕五花海一圈九寨沟约等于白来'): ("correct", ""),
    ('P4_建议推断', '九寨沟', '时间条件句内', '像我一样放慢生活的节奏择一假期带着心爱的人一起置身于山水草木之间过几天向往已久的'): ("boundary", "不妨建议成立，条件弱关联"),
    ('P4_建议推断', '九寨沟', '一般建议', '在环形栈道走一圈这个点太阳已经出来了照得每个角度的海子颜色都不一样五眼六色的特别'): ("correct", ""),
    ('P4_建议推断', '颐和园', '一般建议', '上去看看非常的漂亮'): ("boundary", "条件应为“体力可以”"),
    ('P4_建议推断', '颐和园', '一般建议', '买联票更省心'): ("correct", "与样本43“不要买联票”构成游客间的对立建议"),
    ('P4_建议推断', '颐和园', '一般建议', '经常出行了'): ("wrong", "行李箱广告文案"),
    ('P4_建议推断', '颐和园', '一般建议', '帮忙点赞和收藏'): ("wrong", "博主求赞，非旅游建议"),
    ('P4_建议推断', '颐和园', '一般建议', '预留一整天'): ("correct", ""),
    ('P4_建议推断', '黄山', '一般建议', '是离汤口镇南门游客中心白色椭圆天桥近一点的地方爬完回去休息非常方便'): ("boundary", "“住宿最好是…”为位置建议，条件缺省"),
    ('P4_建议推断', '黄山', '一般建议', '自由行没有旅行团走这条线北大门到西大门只能包车'): ("boundary", "条件应为“自由行”人群"),
    ('P4_建议推断', '黄山', '一般建议', '天数:三至七天左右不计往返时间'): ("boundary", "“建议天数”信息型标签"),
    ('P4_建议推断', '黄山', '一般建议', '查了下淘宝有很多黄山的店铺卖当季新茶的'): ("wrong", "长句杂揉，建议为叙述"),
    ('P4_建议推断', '黄山', '一般建议', '大家尽量以独卫床为主性价比最高标间价格过贵公卫条件过差'): ("correct", ""),
    ('P5_人群可以', '九寨沟', '游客为体力不足', '观光车➕缆车下'): ("correct", ""),
    ('P5_人群可以', '颐和园', '游客为体力差的朋友', '不登去下一站画中游同样好看——画中游在半山腰俯瞰昆明湖远眺西山'): ("correct", ""),
    ('P5_人群可以', '颐和园', '游客为体力好的还', '继续沿湖往南走~'): ("boundary", "人群拖尾“体力好的还”"),
    ('P5_人群可以', '黄山', '游客为体力好的话', '从云谷寺索道走后山—前山的经典线路'): ("correct", ""),
    ('P6_否定建议', '九寨沟', '一般建议避雷', '那样要走两公里多哦'): ("boundary", "建议对但被括号截断"),
    ('P6_否定建议', '九寨沟', '一般建议避雷', '不要期望和她们商量让你插下队素质很一般'): ("wrong", "抱怨叙述"),
    ('P6_否定建议', '九寨沟', '一般建议避雷', '不要成为第二个峨眉山猴群被游客宠得嚣张跋扈'): ("wrong", "愿望表达"),
    ('P6_否定建议', '九寨沟', '装备条件句内', '避免污染环境还是文明入厕的好'): ("boundary", "条件类型误标装备"),
    ('P6_否定建议', '九寨沟', '一般建议避雷', '不要慌忙赶路要稳要适应高海拔'): ("correct", ""),
    ('P6_否定建议', '颐和园', '一般建议避雷', '不要排了当天的票没了啊~~~~~旁边有人说在携程还能买到票'): ("wrong", "对话场景转述"),
    ('P6_否定建议', '颐和园', '装备条件句内', '慎重考虑'): ("boundary", "建议对，条件应为人群（带老人或小朋友）"),
    ('P6_否定建议', '颐和园', '一般建议避雷', '不要硬打卡全部点位挑重点慢走细逛'): ("correct", ""),
    ('P6_否定建议', '颐和园', '一般建议避雷', '不要相信兜售东西的小商贩每个景点附近都有正规的商店或者打车的地方'): ("correct", ""),
    ('P6_否定建议', '颐和园', '一般建议避雷', '不要买联票'): ("correct", ""),
    ('P6_否定建议', '黄山', '一般建议避雷', '不要在任何建筑物古迹岩石竹木上题字刻画'): ("correct", ""),
    ('P6_否定建议', '黄山', '装备条件句内', '避免低血糖'): ("boundary", "“不建议…”被负向守卫跳过，尾部条件应为身体不适"),
    ('P6_否定建议', '黄山', '一般建议避雷', '不要太多'): ("wrong", "“好了不要太多”口语比较"),
    ('P6_否定建议', '黄山', '一般建议避雷', '不要把祖宗留下来的宝贵东西毁在我们手上'): ("wrong", "呼吁管理者，非对读者的建议"),
    ('P6_否定建议', '黄山', '装备条件句内', '就算外面很热地板也很凉我冷到有点灵魂出窍了默默把我的薄羽绒穿上了…我其实带了一个'): ("boundary", "“避免睡地板”建议对，条件类型误标装备"),
}


def load() -> list[dict]:
    return [json.loads(l) for l in (OUT / "conditional_pairs.jsonl").open(encoding="utf-8")]


def sample(pairs: list[dict]) -> None:
    cells: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, p in enumerate(pairs):
        cells[(p["pattern"].split("_")[0], p["scenic_area"])].append(i)
    rng = random.Random(SEED)
    picks = []
    for cell in sorted(cells):
        pool = cells[cell]
        picks.extend(rng.sample(pool, min(N_PER_CELL, len(pool))))
    out = []
    for i in picks:
        p = pairs[i]
        out.append({"case_index": i, "pattern": p["pattern"], "scenic_area": p["scenic_area"],
                    "condition": p["condition_text"], "suggestion": p["suggestion_text"],
                    "sentence": p["sentence"]})
    (OUT / "review_sample.json").write_text(
        json.dumps({"seed": SEED, "n_per_cell": N_PER_CELL, "samples": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    for j, s in enumerate(out):
        key = (s["pattern"], s["scenic_area"], _norm(s["condition"])[:24], _norm(s["suggestion"])[:40])
        tag = "已判" if key in VERDICTS else "未判"
        print(f"{j:2d}[{tag}] [{s['pattern']}|{s['scenic_area']}] 条件:{s['condition'][:26]} | 建议:{s['suggestion'][:40]}")
        print(f"    句: {s['sentence'][:100]}")


def fill(pairs: list[dict]) -> None:
    data = json.loads((OUT / "review_sample.json").read_text(encoding="utf-8"))
    rows = []
    for j, s in enumerate(data["samples"]):
        key = (s["pattern"], s["scenic_area"], _norm(s["condition"])[:24], _norm(s["suggestion"])[:40])
        if key not in VERDICTS:
            continue
        verdict, note = VERDICTS[key]
        rows.append({**s, "verdict": verdict, "note": note})
    (OUT / "review_gold.json").write_text(
        json.dumps({"n": len(rows), "reviews": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"review written: {len(rows)}")


def score() -> None:
    data = json.loads((OUT / "review_gold.json").read_text(encoding="utf-8"))["reviews"]
    c = Counter(r["verdict"] for r in data)
    by_pattern = defaultdict(lambda: Counter())
    for r in data:
        by_pattern[r["pattern"].split("_")[0]][r["verdict"]] += 1
    result = {"n": len(data), "verdicts": dict(c),
              "by_pattern": {k: dict(v) for k, v in by_pattern.items()}}
    (OUT / "review_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def charts() -> None:
    stats = json.loads((OUT / "extraction_stats.json").read_text(encoding="utf-8"))
    mapping = json.loads((OUT / "mapping_table.json").read_text(encoding="utf-8"))
    FIGS.mkdir(parents=True, exist_ok=True)

    # 图1：条件类型 × 景区（按频次加权）
    types = ["人群", "天气", "时间", "装备", "预约票务", "交通", "体力安全", "一般", "其他"]
    areas = ["黄山", "九寨沟", "颐和园"]
    weighted = {a: Counter() for a in areas}
    for m in mapping:
        weighted[m["scenic_area"]][m["condition_type"]] += m["frequency"]
    import numpy as np
    x = np.arange(len(types))
    width = 0.26
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=150)
    for i, a in enumerate(areas):
        vals = [weighted[a].get(t, 0) for t in types]
        ax.bar(x + (i - 1) * width, vals, width, label=a, alpha=0.85)
    ax.set_xticks(x, types, rotation=20)
    ax.set_ylabel("条件→建议对数量（含频次）")
    ax.set_title("条件性建议的类型 × 景区分布")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "cond_type_by_scenic.png")
    plt.close(fig)

    # 图2：人群类细分（游客类型）
    crowd = Counter()
    for m in mapping:
        if m["condition_type"] == "人群":
            for w, label in (("老人", "老人"), ("孩子", "孩子"), ("小孩", "孩子"), ("儿童", "孩子"),
                             ("婴儿", "孩子"), ("亲子", "亲子"), ("带娃", "亲子"), ("情侣", "情侣"),
                             ("夫妻", "情侣"), ("孕妇", "孕妇"), ("腿脚", "行动不便"), ("体力", "体力有限"),
                             ("新手", "新手"), ("第一次", "初次游览"), ("学生", "学生"), ("家庭", "家庭"),
                             ("恐高", "恐高"), ("晕车", "晕车")):
                if w in m["condition_text"]:
                    crowd[label] += m["frequency"]
                    break
            else:
                crowd["未细分"] += m["frequency"]
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=150)
    items = crowd.most_common()
    ax.bar([k for k, _ in items], [v for _, v in items], 0.55, color="#C62828", alpha=0.85)
    ax.set_title("人群类条件建议的游客类型分布")
    ax.set_ylabel("对数（含频次）")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / "crowd_breakdown.png")
    plt.close(fig)
    print(json.dumps({"figs": ["cond_type_by_scenic.png", "crowd_breakdown.png"],
                      "crowd": dict(crowd)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--fill", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--charts", action="store_true")
    args = parser.parse_args()
    pairs = load()
    if args.sample:
        sample(pairs)
    elif args.fill:
        fill(pairs)
    elif args.score:
        score()
    elif args.charts:
        charts()
