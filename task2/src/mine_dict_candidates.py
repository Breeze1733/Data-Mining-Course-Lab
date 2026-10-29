# -*- coding: utf-8 -*-
"""P2 词典查全：对未入词典的高频分词结果做系统复核的候选挖掘。

对 271 条清洗文本用 jieba（加载用户词典）分词，统计词频，排除：
  已入词典(POI/交通)、领域停用词、时间正则覆盖、纯数字/ASCII/单字、常见通用词。
输出 top 候选 + 每词 2 条上下文，落盘 task2/output/exp2/dict_candidates.json 供人工复核。

用法：python src/mine_dict_candidates.py [--top 160]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK1 = ROOT.parent / "task1"
OUT = ROOT / "output/exp2"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

TIMEISH = re.compile(
    r"^[\d:：.．\-—~～半几个小时分钟秒日号月份周年点早晚上下午凌晨 nightdaysyhmgk]+$")
ASCII_RE = re.compile(r"^[\x00-\x7F～—…·]+$")
GENERIC_STOP = {
    "我们", "他们", "自己", "大家", "游客", "时候", "时间", "地方", "感觉", "觉得",
    "直接", "然后", "接着", "终于", "开始", "结束", "到达", "抵达", "出发", "返回",
    "推荐", "建议", "攻略", "行程", "安排", "体验", "不错", "可以", "一定", "特别",
    "非常", "真的", "很多", "没有", "就是", "还是", "这个", "那个", "这里", "那里",
    "里面", "外面", "旁边", "附近", "一路", "一起", "一下", "一点", "有些", "有点",
    "风景", "景色", "美景", "风光", "拍照", "照片", "图片", "打卡", "出片", "机位",
    "门票", "票价", "排队", "人多", "人少", "错峰", "旺季", "淡季", "周末", "假期",
    "早上", "上午", "中午", "下午", "傍晚", "晚上", "夜晚", "白天", "全天", "当天",
    "第二天", "第一天", "第三天", "第四天", "半天", "一天", "两天", "三日", "四日",
    "景区", "景点", "园区", "山区", "山脚", "山腰", "山顶", "山上", "山下", "谷底",
    "入口", "出口", "门口", "大门", "检票口", "游客中心", "服务中心", "换乘", "转运",
    "酒店", "民宿", "客栈", "宾馆", "饭店", "餐厅", "餐馆", "美食", "小吃", "早餐",
    "午餐", "晚餐", "住宿", "入住", "房间", "老板", "服务员", "司机", "导游",
    "价格", "费用", "优惠", "折扣", "免费", "收费", "消费", "预算", "花费",
    "交通", "自驾", "包车", "拼车", "打车", "乘车", "坐车", "步行", "徒步", "骑行",
    "爬山", "登山", "上山", "下山", "缆车", "索道", "观光车", "大巴", "班车", "公交",
    "地铁", "高铁", "火车", "飞机", "机场", "车站", "码头", "栈道", "步道", "栈桥",
    "观景台", "平台", "亭子", "长廊", "石碑", "塑像", "佛像", "寺庙", "古寺", "寺院",
    "湖边", "湖畔", "湖面", "海边", "江边", "桥头", "桥上", "洞口", "泉水", "溪水",
    "瀑布群", "彩林", "红叶", "枫叶", "樱花", "桃花", "荷花", "雪景", "雪地", "云海",
    "日出", "日落", "夕阳", "晚霞", "星空", "夜景", "天气", "下雨", "下雪", "晴天",
    "阴天", "气温", "温度", "海拔", "高原", "体力", "膝盖", "鞋子", "装备", "行李",
    "雨衣", "雨伞", "防晒", "墨镜", "帽子", "手套", "拐杖", "登山杖", "氧气", "药物",
    "口罩", "身份证", "护照", "学生", "老人", "孩子", "小孩", "儿童", "婴儿", "情侣",
    "家庭", "朋友", "闺蜜", "爸妈", "老妈", "老爸", "女儿", "儿子", "老公", "老婆",
    "手机", "相机", "充电", "信号", "网络", " wifi", "厕所", "洗手间", "垃圾", "卫生",
    "安全", "危险", "注意", "小心", "事故", "救援", "医院", "药店", "超市", "商店",
    "小卖部", "便利店", "纪念品", "特产", "水果", "矿泉水", "饮料", "零食", "面包",
    "泡面", "自热", "干粮", "巧克力", "咖啡", "奶茶", "啤酒", "白酒", "酸奶", "烤肉",
    "火锅", "串串", "面馆", "米粉", "米饭", "面条", "饺子", "包子", "馒头", "粥",
}


def mine(top_n: int) -> list[dict]:
    sys.path.insert(0, str(TASK1 / "src"))
    entries, stopwords, _ = refined_dictionary()
    dict_names = {e["name"] for e in entries}
    dict_canon = {e.get("canonical") for e in entries}
    userdict_lines = (OUT / "entity_userdict.txt").read_text(encoding="utf-8").splitlines()
    for ln in userdict_lines:
        w = ln.split()[0].strip()
        if w:
            dict_names.add(w)

    import jieba
    jieba.load_userdict(str(OUT / "entity_userdict.txt"))
    jieba.setLogLevel(60)

    freq: Counter = Counter()
    ctx: dict[str, list[str]] = {}
    rows = [json.loads(l) for l in
            (TASK1 / "data/processed/dataset_clean.jsonl").open(encoding="utf-8")]
    for row in rows:
        text = row["clean_content"]
        for w in jieba.cut(text):
            w = w.strip()
            if len(w) < 2 or len(w) > 8:
                continue
            if w in dict_names or w in dict_canon or w in stopwords or w in GENERIC_STOP:
                continue
            if TIMEISH.search(w) or ASCII_RE.search(w) or w.isdigit():
                continue
            if re.search(r"[一二三四五六七八九十百千万亿]", w) and len(w) <= 3:
                continue
            freq[w] += 1
            if w not in ctx:
                ctx[w] = []
            if len(ctx[w]) < 2:
                i = text.find(w)
                if i >= 0:
                    ctx[w].append(text[max(0, i - 18):i + len(w) + 18].replace("\n", " "))

    cands = [{"word": w, "freq": n, "contexts": ctx[w]}
             for w, n in freq.most_common(top_n) if n >= 3]
    return cands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=160)
    args = ap.parse_args()

    from entity_rules import refined_dictionary  # noqa: E402  (需要在 sys.path 之后)
    globals()["refined_dictionary"] = refined_dictionary
    cands = mine(args.top)
    out_path = OUT / "dict_candidates.json"
    out_path.write_text(json.dumps(
        {"note": "P2 候选挖掘：jieba 词频(去已入词典/停用词/时间/通用词)，供人工复核增补词典",
         "n": len(cands), "candidates": cands}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"候选 {len(cands)} 个 -> {out_path.name}")
    for c in cands[:60]:
        print(f"{c['freq']:4d}  {c['word']}  |  {c['contexts'][0] if c['contexts'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
