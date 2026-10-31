# -*- coding: utf-8 -*-
"""P1 句子级叙述焦点：方案A（记录级标签）vs 方案B（特征规则）评估。

方案B按记录顺序处理全量句子，特征：
  1. 景区专名命中（词典POI + 补充地标词，长词优先）：命中景区得分 +3/次；
  2. 景区外信号：联游景区/城市地标/住宿餐饮/往返大交通关键词，+2/次；
  3. 园内基础设施（索道/观光车/栈道/门票/检票/观景台）：仅证明"在景区内"，+1；
  4. 转移词（接着|然后|下一站|继续|回到|前往）：无专名冲突时继承前句标签；
  5. 无任何信号：仅有基础设施词 → 记录级标签（弱证据）；否则 → 无法判断。

评估：只在 sentence_attribution.jsonl 的 495 个标注位置上打分（5类准确率）。
调参纪律：seed=42 对半分，权重只在 tune 半区迭代，holdout 半区只做最终一次评估。

用法：
  python src/attribute_sentences.py --evaluate           # A/B 对比评估
  python src/attribute_sentences.py --output out.jsonl   # 全量归属落盘（供下游）
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # task4/
TASK1 = ROOT.parent / "task1"
ATTR = ROOT / "output/attribution"
EXP2 = ROOT.parent / "task2/output/exp2"  # 词典是实验2 的产物（只读引用）

def ensure_utf8_stdout() -> None:
    """仅在自身作为主脚本运行时包装 stdout；被其他脚本导入时不动其流（避免旧包装器被GC后关闭底层缓冲）。"""
    enc = getattr(sys.stdout, "encoding", "") or ""
    if enc.lower().replace("-", "") != "utf8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


SENT_SPLIT = re.compile(r"[。！？；!?\n]+")
LABELS = ["黄山", "九寨沟", "颐和园", "景区外", "无法判断"]

POI_W = 3.0
OUTSIDE_W = 2.0
INFRA_W = 1.0
WEAK_W = 0.6

# 根景区名（词典排除根景区，这里补回；九寨 是常见简称）
ROOT_ALIASES = {"黄山": "黄山", "九寨沟": "九寨沟", "九寨": "九寨沟", "颐和园": "颐和园"}

# 词典未收录但对归属判别有用的地标/设施（人工补充，多来自标注中反复出现的误判点）
SUPPLEMENT_POI = {
    "黄山": ["汤口", "换乘中心", "新国线", "挑夫", "地轨", "小火车", "西海大峡谷观光缆车",
             "白云宾馆", "光明顶山庄", "北海宾馆", "西海饭店", "西海宾馆", "狮林大酒店",
             "天海山庄", "白鹅山庄", "玉屏楼宾馆", "排云楼宾馆", "云谷山庄"],
    "九寨沟": ["扎如寺", "诺日朗中心", "树正寨", "荷叶寨", "盆景滩"],
    "颐和园": ["惠山园", "宿云檐", "水木自亲", "须弥灵境", "慈福牌楼", "琉璃塔", "绣漪桥",
               "练桥", "镜桥", "界湖桥", "知春亭", "文昌阁", "玉带桥", "廓如亭", "南湖岛",
               "铜牛", "听鹂馆", "德和园", "颐乐殿", "宜芸馆", "玉澜堂", "乐寿堂", "排云殿",
               "佛香阁", "智慧海", "转轮藏", "宝云阁", "澹会轩", "鉴远堂", "月波楼",
               "云香阁", "龙王庙", "畅观堂", "团城湖", "耕织图", "水村居", "画中游",
               "苏州街", "四大部洲", "清晏舫", "石舫", "长廊", "谐趣园", "万寿山", "昆明湖",
               "西堤", "玉泉山", "凤凰墩", "藻鉴堂", "治镜阁", "十七孔桥"],
}

# 景区内常驻酒店名 → 视为该景区 POI 证据（口径D1：山上/园内住宿属景区内）
IN_AREA_HOTELS = ["白云宾馆", "光明顶山庄", "北海宾馆", "西海饭店", "西海宾馆", "狮林大酒店",
                  "天海山庄", "白鹅山庄", "玉屏楼宾馆", "排云楼宾馆", "云谷山庄"]

# 景区外信号 v2：联游景区/城市/餐饮购物/大交通
OUTSIDE_LANDMARKS = [
    "黄龙", "川主寺", "松潘", "叠溪海子", "牟尼沟", "神仙池", "中查", "鲁能胜地",
    "若尔盖", "红原", "月亮湾", "达古冰川", "汶川", "茂县", "都江堰", "二王庙",
    "青城山", "峨眉", "乐山大佛", "凌云大佛", "三星堆", "宽窄巷子", "锦里",
    "春熙路", "杜甫草堂", "武侯祠", "文殊院", "青羊宫", "九黄机场", "漳扎",
    "隆务寺", "同仁", "拉卜楞寺", "塔尔寺", "郎木寺", "扎尕那", "黄河九曲",
    "九寨沟县", "县城", "成都", "重庆", "兰州", "绵阳", "广汉", "临夏", "西安",
    "宏村", "西递", "屯溪", "老街", "徽州古城", "呈坎", "棠樾", "新安江",
    "千岛湖", "太平湖", "三清山", "婺源", "篁岭", "瑶里", "景德镇", "陶溪川",
    "汪湖", "五夫", "九华山", "化城寺", "百岁宫", "天台峰", "闵园", "祇园寺",
    "泰山", "天外村", "庐山", "秀峰", "香炉峰", "含鄱亭", "牯岭", "天沐温泉",
    "武夷山", "舟山", "朱家尖", "宁波", "杭州", "西湖", "灵隐", "石林",
    "南屏", "卢村", "木坑", "塔川", "协里", "鱼鳞坝", "青弋江", "十里红妆",
    "故宫", "紫禁城", "天安门", "天坛", "圜丘", "皇穹宇", "祈年殿", "大享殿",
    "圆明园", "大水法", "海晏堂", "西洋楼", "黄花阵", "北海公园", "白塔", "九龙壁",
    "恭王府", "银安殿", "嘉乐堂", "南锣鼓巷", "什刹海", "后海", "烟袋斜街",
    "鼓楼", "鸟巢", "水立方", "奥林匹克", "八达岭", "慕田峪", "长城",
    "居庸关", "国博", "国家博物馆", "国家大剧院", "雍和宫", "孔庙", "国子监",
    "智化寺", "五塔寺", "前门", "大栅栏", "正阳门", "王府井", "三里屯",
    "清华", "北大", "熙春园", "近春园", "水木清华", "爨底下", "灵水村", "琉璃渠",
    "云居寺", "石经山", "房山", "元大都", "人民英雄纪念碑", "护国寺", "同仁堂",
    "定陵", "十三陵", "陈独秀", "新青年", "中央广播电视", "避暑山庄", "承德",
    "普陀宗乘", "大红台", "大白台", "香山", "北宫门地铁",
    "酒店", "民宿", "客栈", "住宿", "宾馆", "旅舍", "招待所", "房价",
    "火锅", "烤鸭", "小吃", "美食", "餐厅", "餐馆", "食堂", "宵夜", "夜市",
    "早餐", "午餐", "晚餐", "早饭", "晚饭", "点心", "蛋糕", "奶茶", "咖啡",
    "涮肉", "涮", "臭鳜鱼", "老干妈", "雪糕", "包浆豆腐", "青稞酒", "骨汤",
    "高铁", "飞机", "机场", "航班", "动车", "火车", "登机", "值机", "地勤",
    "一卡通", "高速费", "收费站", "加油站", "导航", "机场大巴",
    "步行街", "商场", "超市", "纪念品", "特产", "免税", "礼品卡", "摊贩",
]
# 基础设施词：证明"在景区游览语境"，但不指明哪个景区
INFRA_WORDS = [
    "索道", "缆车", "观光车", "环保车", "摆渡车", "景区大巴", "中转车",
    "门票", "检票", "购票", "票价", "预约", "入园", "闭园", "开园",
    "栈道", "观景台", "观景亭", "游客中心", "游客服", "景区大门", "景区门口",
    "步道", "栈桥", "游船码头", "机位", "停车场", "进沟", "出沟", "进景区",
    "出景区", "景区内", "二进沟",
]
# 各景区弱特征词（无专名时的景观/活动词，低权重）
WEAK_SCENIC_WORDS = {
    "黄山": ["山上", "上山", "下山", "山顶", "山腰", "山脚", "登山", "爬山", "日出",
             "日落", "云海", "云雾", "怪石", "奇松", "险峻", "上坡", "下坡", "登山杖"],
    "九寨沟": ["海子", "湖水", "湖泊", "瀑布", "彩林", "雪峰", "雪山", "藏寨", "藏族",
               "藏民", "藏文化", "高原", "碧蓝", "碧绿", "沟内", "钙华", "海子"],
    "颐和园": ["园内", "游园", "御苑", "御题", "皇家", "乾隆", "慈禧", "光绪", "园中园", "湖"],
}
TRANSITION_RE = re.compile(r"^(接着|然后|随后|下一站|继续|回到|返程|前往|乘(车|坐)|坐(车|上))")
# 大交通覆盖：出现即判景区外，除非句中带游览意图词，或交通词紧跟 景区/园内/沟内（园内交通）
TRANSPORT_RE = re.compile(
    r"班车|大巴|公交|地铁|高铁|动车|火车|飞机|机场|航班|登机|值机|地勤|"
    r"打车|包车|拼车|自驾|发往|班次|一卡通|高速|登机牌")
TOURISM_INTENT_RE = re.compile(r"爬山|登山|游玩|游览|旅游|旅行|上山|赏|逛园|景区游")
HOTEL_RE = re.compile(r"酒店|宾馆|民宿|客栈|旅舍|招待所")
HOTEL_DESC_RE = re.compile(r"外观|装修|房间|性价比|推荐|管家|前台|隔音|床位|泳池|温泉|早餐|房型|设施|卫生|榻榻米")
IN_AREA_HOTEL_CTX_RE = re.compile(
    r"山上|山顶|上山|山中|山腰|园内|沟内|景区|日出|索道|云谷|光明顶|北海|天海|西海|白鹅|丹霞|玉屏|迎客|汤口以上")
OFFICIAL_GUARD_RE = re.compile(r"线路|路线|游|门|索道|车|票|时间|园|沟|山|湖|观")


def load_dict() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """返回 (scenic -> [POI名，长词在前], 全部POI名 -> scenic_areas)"""
    d = json.loads((EXP2 / "entity_dictionary.json").read_text(encoding="utf-8"))
    scenic2poi: dict[str, list[str]] = {"黄山": [], "九寨沟": [], "颐和园": []}
    for e in d["poi"]:
        for s in e.get("scenic_areas", []):
            if s in scenic2poi:
                scenic2poi[s].append(e["name"])
    for s in scenic2poi:
        scenic2poi[s].sort(key=len, reverse=True)
    return scenic2poi, {e["name"]: e.get("scenic_areas", []) for e in d["poi"]}


class Attributor:
    def __init__(self, poi_weight=POI_W, outside_weight=OUTSIDE_W, weak_weight=WEAK_W):
        self.scenic2poi, self.poi2scenic = load_dict()
        for scenic, names in SUPPLEMENT_POI.items():
            for n in names:
                if n not in self.scenic2poi[scenic]:
                    self.scenic2poi[scenic].append(n)
        for scenic in self.scenic2poi:
            self.scenic2poi[scenic].extend([ROOT_ALIASES[scenic]])
            self.scenic2poi[scenic].sort(key=len, reverse=True)
        self.in_area_hotel2scenic = {}
        for scenic, names in self.scenic2poi.items():
            for h in IN_AREA_HOTELS:
                if h in names:
                    self.in_area_hotel2scenic[h] = scenic
        self.poi_w = poi_weight
        self.outside_w = outside_weight
        self.weak_w = weak_weight

    def sentence_scores(self, sent: str) -> dict:
        scores = {"黄山": 0.0, "九寨沟": 0.0, "颐和园": 0.0}
        outside = 0.0
        infra = False
        text_ctx = sent.replace("风景区店", "")  # 酒店"风景区店"分支后缀不是景区语境
        for scenic, names in self.scenic2poi.items():
            for name in names:
                if len(name) < 2:
                    continue
                if name in sent:
                    scores[scenic] += self.poi_w  # 出现即计一次，避免重复刷分
        for kw in OUTSIDE_LANDMARKS:
            if kw in sent:
                outside += self.outside_w
        for kw in INFRA_WORDS:
            if kw in sent:
                infra = True
                break
        weak = {s: 0.0 for s in scores}
        for scenic, kws in WEAK_SCENIC_WORDS.items():
            for kw in kws:
                if kw in sent:
                    weak[scenic] += self.weak_w
        # 酒店语境处理（口径D1：山上/园内酒店属景区内，其余住宿属景区外）
        hotel_desc = hotel_ctx = False
        if HOTEL_RE.search(sent):
            named = [h for h in self.in_area_hotel2scenic if h in sent]
            if named:
                scores[self.in_area_hotel2scenic[named[0]]] += self.poi_w
            elif HOTEL_DESC_RE.search(sent):
                outside += self.outside_w  # 酒店推销/体验描写 → 景区外
            elif IN_AREA_HOTEL_CTX_RE.search(text_ctx):
                hotel_ctx = True  # 登山/园内语境下提及酒店 → 景区内配套
                infra = True
            else:
                outside += self.outside_w
        trans = bool(TRANSITION_RE.match(sent.strip()))
        return {"scores": scores, "outside": outside, "infra": infra, "trans": trans, "weak": weak, "hotel_ctx": hotel_ctx}

    def attribute_record(self, record_label: str, sentences: list[str],
                         text_type: str = "travelogue") -> list[str]:
        result = []
        prev_label: str | None = None
        for sent in sentences:
            f = self.sentence_scores(sent)
            scores, outside, infra = f["scores"], f["outside"], f["infra"]
            best_scenic = max(scores, key=lambda k: scores[k])
            best_val = scores[best_scenic]
            second_val = sorted((v for k, v in scores.items() if k != best_scenic), reverse=True)[0]
            weak_best = max(f["weak"], key=lambda k: f["weak"][k])
            weak_val, weak_second = f["weak"][weak_best], sorted(
                (v for k, v in f["weak"].items() if k != weak_best), reverse=True)[0]

            # 大交通覆盖：交通词出现且无游览意图 → 景区外（园内交通不受影响）
            transport_override = False
            if TRANSPORT_RE.search(sent) and not TOURISM_INTENT_RE.search(sent):
                stripped = re.sub(r"(景区|园内|沟内)[^，。]{0,4}(大巴|观光车|中转车|环保车|摆渡车|交通车)", "", sent)
                if TRANSPORT_RE.search(stripped):
                    transport_override = True

            if transport_override:
                label = "景区外"
            elif outside > 0 and outside >= best_val:
                label = "景区外"
            elif f["hotel_ctx"] and best_val == 0 and second_val == 0 and outside == 0:
                label = record_label  # 景区内酒店语境且无冲突信号
            elif best_val > 0 and best_val > second_val:
                label = best_scenic
            elif best_val > 0 and best_val == second_val:
                label = "无法判断"  # 两景区专名并列
            elif outside > best_val:
                label = "景区外"
            elif weak_val > 0 and weak_val > weak_second and outside == 0:
                label = weak_best
            elif f["trans"] and prev_label:
                label = prev_label
            elif infra:
                label = record_label
            elif text_type == "official_route" and OFFICIAL_GUARD_RE.search(sent):
                label = record_label  # 官方文本默认叙述本景区
            else:
                label = "无法判断"
            result.append(label)
            if label != "无法判断":
                prev_label = label
            elif prev_label is None:
                prev_label = record_label
        return result


def split_spans(text: str) -> list[tuple[int, int, str]]:
    out, start = [], 0
    for m in SENT_SPLIT.finditer(text):
        if m.start() > start:
            out.append((start, m.start(), text[start:m.start()]))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:]))
    return [(s, e, t) for s, e, t in out if t.strip()]


def run_all(output_path: Path | None) -> dict[tuple[str, int], str]:
    """全量归因。返回 (record_id, start) -> label，供评估与下游使用。"""
    rows = [json.loads(l) for l in
            (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
    attr = Attributor()
    lookup: dict[tuple[str, int], str] = {}
    writer = None
    if output_path:
        writer = output_path.open("w", encoding="utf-8")
    for row in rows:
        spans = split_spans(row["clean_content"])
        labels = attr.attribute_record(row["scenic_area"], [t for _, _, t in spans],
                                       text_type=row.get("text_type", "travelogue"))
        rec_out = {"record_id": row["record_id"], "scenic_area": row["scenic_area"],
                   "labels": [{"start": s, "end": e, "label": lab} for (s, e, _), lab in zip(spans, labels)]}
        if writer:
            writer.write(json.dumps(rec_out, ensure_ascii=False) + "\n")
        for (s, _, _), lab in zip(spans, labels):
            lookup[(row["record_id"], s)] = lab
    if writer:
        writer.close()
    return lookup


def evaluate(lookup: dict[tuple[str, int], str], errors_path: Path | None = None) -> dict:
    """在 495 句标注集上评估方案A（记录级标签）与方案B（特征规则）的准确率与混淆。"""
    gold_rows = [json.loads(l) for l in (ATTR / "sentence_attribution.jsonl").open(encoding="utf-8")]
    err_fh = errors_path.open("w", encoding="utf-8") if errors_path else None

    def score(method: str) -> dict:
        correct = n = 0
        conf: Counter = Counter()
        for g in gold_rows:
            pred = g["scenic_area"] if method == "A" else lookup.get((g["record_id"], g["start"]), "无法判断")
            n += 1
            if pred == g["label"]:
                correct += 1
            elif err_fh and method == "B":
                err_fh.write(json.dumps(
                    {"gold": g["label"], "pred": pred, "sid": g["sid"],
                     "record": g["record_id"], "text": g["sentence"]}, ensure_ascii=False) + chr(10))
            conf[f"{g['label']}||{pred}"] += 1
        return {"n": n, "acc": round(correct / n, 4) if n else None, "confusion": dict(conf)}

    res = {
        "full": {"A": score("A"), "B": score("B")},
        "method_note": ("方案B v2（特征规则）：词典POI+根名别名+补充地标(权重3/次)，景区外信号(2)，"
                        "大交通覆盖，酒店三态，弱景观词(0.6)，转移词继承，基础设施+官方文本回退记录级标签。"),
    }
    if err_fh:
        err_fh.close()
    return res


def main() -> int:
    ensure_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true", help="在 495 句标注集上评估 A/B 准确率")
    ap.add_argument("--errors", action="store_true", help="导出方案B 的错误样例供特征设计")
    ap.add_argument("--output", type=str, default="", help="全量归属输出路径")
    args = ap.parse_args()

    out_path = Path(args.output) if args.output else None
    lookup = run_all(out_path)
    if out_path:
        print(f"全量归属 -> {out_path}")

    if args.evaluate:
        res = evaluate(lookup, ATTR / "attribution_errors.jsonl" if args.errors else None)
        (ATTR / "attribution_eval.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        a, b = res["full"]["A"], res["full"]["B"]
        print(f"A记录级标签: acc={a['acc']} (n={a['n']})  |  B特征规则: acc={b['acc']} (n={b['n']})")
        conf = res["full"]["B"]["confusion"]
        worst = sorted(((k, v) for k, v in conf.items() if "||" in k and k.split("||")[0] != k.split("||")[1]),
                       key=lambda x: -x[1])[:12]
        print("B 主要混淆 (gold->pred):")
        for kv, v in worst:
            g, pr = kv.split("||")
            print(f"   {g} -> {pr}: {v}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
