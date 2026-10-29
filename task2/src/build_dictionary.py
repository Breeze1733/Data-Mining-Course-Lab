"""实验2：构建三类实体的自定义词典与定义规范。

流程：
  1. jieba 分词统计全语料词频，按 POI 后缀（海/峰/阁/桥…）挖掘候选专名（阈值 ≥8 次）；
  2. 人工复核候选表，剔除通名（山峰/下山/知道类）与无关地名（上海/庐山类），确认专名归属景区；
  3. 合并采集阶段的景区 POI 种子（expand_ctrip.NODES）与本文件中的人工整理词条；
  4. 输出 entity_dictionary.json（机器可读）、entity_userdict.txt（jieba 自定义词典）、entity_schema.md（定义规范表）。

时间节点不走词典，由 extract_entities.py 的正则规则识别（时刻/时段/时长/日期四类）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # task2/
OUT = ROOT / "output/exp2"

# ── 景点 POI（人工整理：来源 = 采集种子 expand_ctrip.NODES ∪ 词频挖掘候选，2026-10-29 复核）──
POIS: dict[str, list[str]] = {
    "黄山": [
        "迎客松", "天都峰", "莲花峰", "光明顶", "玉屏楼", "慈光阁", "云谷寺", "白鹅岭",
        "始信峰", "飞来石", "排云亭", "西海大峡谷", "鳌鱼峰", "百步云梯", "一线天",
        "猴子观海", "梦笔生花", "黑虎松", "连理松", "竖琴松", "探海松", "麒麟松",
        "丹霞峰", "狮子峰", "清凉台", "曙光亭", "散花坞", "石笋矼", "半山寺", "天海",
        "北海", "西海", "松谷庵", "云谷", "玉屏", "九龙瀑", "翡翠谷", "宏村", "屯溪老街",
    ],
    "九寨沟": [
        "长海", "五彩池", "五花海", "珍珠滩瀑布", "珍珠滩", "熊猫海瀑布", "熊猫海",
        "箭竹海瀑布", "箭竹海", "镜海", "犀牛海", "老虎海", "火花海", "芦苇海", "双龙海",
        "卧龙海", "树正群海", "树正瀑布", "树正寨", "荷叶寨", "盆景滩", "芳草海", "天鹅海",
        "原始森林", "诺日朗瀑布", "诺日朗游客中心", "诺日朗", "日则沟", "则查洼沟",
        "树正沟", "扎如沟", "中查沟", "雪峰", "上季节海", "下季节海", "季节海",
        "静心台", "清心台", "归心台", "随心台",  # 原始森林健康游内部节点（实验3解析时发现补录）
        "沟口", "树正磨坊", "树正磨房",  # 实验3解析补录：沟口为景区门户节点
        "五彩池畔", "黄龙", "川主寺", "甘海子", "神仙池", "牟尼沟",
    ],
    "颐和园": [
        "东宫门", "北宫门", "新建宫门", "颐和园西门", "北如意门", "长廊", "昆明湖",
        "东门", "西门", "耕织图", "后溪河",  # 实验3解析补录：门/简称与西区节点
        "万寿山", "佛香阁", "排云殿", "石舫", "清晏舫", "苏州街", "十七孔桥", "铜牛",
        "南湖岛", "西堤", "玉带桥", "界湖桥", "豳风桥", "谐趣园", "文昌阁", "仁寿殿",
        "知春亭", "玉澜堂", "德和园", "乐寿堂", "宜芸馆", "智慧海", "四大部洲", "画中游",
        "听鹂馆", "景福阁", "霁清轩", "廓如亭", "宝云阁", "苏州街",
    ],
}
# 周边景点：不在三景区围墙内、但游记中高频共现的关联景点，单独子类以免污染景区内 POI 词频
SURROUNDING = {
    "黄山": ["九龙瀑", "翡翠谷", "宏村", "屯溪老街"],
    "九寨沟": ["黄龙", "川主寺", "甘海子", "神仙池", "牟尼沟"],
    "颐和园": [],
}
POI_ALIAS = {"清晏舫": "石舫", "诺日朗游客中心": "诺日朗中心", "玉屏": "玉屏景区", "云谷": "云谷景区"}

# ── 交通方式（人工整理词表；subtype 标注出行方式类别）──
TRANSPORT: list[tuple[str, str]] = [
    # (词, subtype)
    ("索道", "索道缆车"), ("缆车", "索道缆车"), ("观光缆车", "索道缆车"),
    ("玉屏索道", "索道缆车"), ("云谷索道", "索道缆车"), ("太平索道", "索道缆车"),
    ("西海观光缆车", "索道缆车"),
    ("观光车", "景区车辆"), ("景区大巴", "景区车辆"), ("摆渡车", "景区车辆"),
    ("环保车", "景区车辆"), ("接驳车", "景区车辆"), ("电瓶车", "景区车辆"),
    ("小火车", "景区车辆"), ("大巴", "景区车辆"), ("巴士", "景区车辆"),
    ("公交车", "公共交通"), ("公交", "公共交通"), ("地铁", "公共交通"),
    ("班车", "公共交通"), ("出租车", "公共交通"), ("网约车", "公共交通"),
    ("高铁", "长途交通"), ("动车", "长途交通"), ("火车", "长途交通"), ("飞机", "长途交通"),
    ("轮渡", "水上交通"), ("渡轮", "水上交通"), ("游船", "水上交通"), ("游轮", "水上交通"),
    ("自驾", "自驾"), ("包车", "自驾"), ("租车", "自驾"),
    ("步行", "步行"), ("徒步", "步行"), ("登山", "步行"), ("骑行", "骑行"),
]

# 领域停用词：分词后形似实体但明确不是实体的通用词（迭代1根据可视化结果加入）
DOMAIN_STOPWORDS = [
    "上海", "北海公园", "景山公园", "圆明园", "天安门", "香山", "八达岭",  # 北京同城干扰
    "庐山", "泰山", "峨眉山", "九华山", "青城山", "三清山", "武夷山", "四姑娘山",  # 其他名山
    "知道", "下山", "上山", "爬山", "公园", "味道", "轻松", "专门", "开门", "出门", "入园", "进沟", "进山",
]

# 景区自身名不算景区内 POI（是“景区”这一层级的名称）
SCENIC_SELF_NAMES = {"黄山", "九寨沟", "九寨", "颐和园"}


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    poi_entries = []
    for area, names in POIS.items():
        for name in dict.fromkeys(names).keys():
            if name in SCENIC_SELF_NAMES:
                continue
            poi_entries.append({
                "name": name, "entity_type": "景点POI", "subtype": "景点",
                "scenic_areas": [area],
                "canonical": POI_ALIAS.get(name, name),
                "source": "seed+manual_review_of_mined_candidates",
            })
    for area, names in SURROUNDING.items():
        for name in names:
            poi_entries.append({
                "name": name, "entity_type": "景点POI", "subtype": "周边景点",
                "scenic_areas": [area], "canonical": name,
                "source": "manual_vocabulary",
            })
    merged: dict[str, dict] = {}
    for e in poi_entries:
        if e["name"] in merged:
            merged[e["name"]]["scenic_areas"] = sorted(set(merged[e["name"]]["scenic_areas"] + e["scenic_areas"]))
        else:
            merged[e["name"]] = e
    transport_entries = []
    for name, subtype in TRANSPORT:
        transport_entries.append({
            "name": name, "entity_type": "交通方式", "subtype": subtype,
            "scenic_areas": ["通用"], "canonical": name, "source": "manual_vocabulary",
        })
    dictionary = {
        "meta": {
            "built_by": "src/exp2/build_dictionary.py",
            "method": "jieba词频挖掘（后缀过滤，阈值≥8）+ 人工复核 + 采集种子合并；时间节点由正则规则识别，不入词典",
            "review_date": "2026-10-29",
            "counts": {"poi": len(merged), "transport": len(transport_entries)},
        },
        "poi": sorted(merged.values(), key=lambda e: e["name"]),
        "transport": transport_entries,
        "domain_stopwords": DOMAIN_STOPWORDS,
    }
    (OUT / "entity_dictionary.json").write_text(json.dumps(dictionary, ensure_ascii=False, indent=1), encoding="utf-8")

    with (OUT / "entity_userdict.txt").open("w", encoding="utf-8") as fh:
        for e in merged.values():
            fh.write(f'{e["name"]} 1000 nz\n')
        for e in transport_entries:
            fh.write(f'{e["name"]} 1000 n\n')

    lines = ["# 实体定义规范表（实验2）", "",
             "适用范围：黄山、九寨沟、颐和园三景区的官方路线与游客游记文本（清洗后）。三个景区共用同一套定义，仅词表不同。", "",
             "## 1. 景点POI", "",
             "- **定义**：文本中被赋予专名、游客可以“到达/游览/拍照”的具体游览对象，包括峰、海（湖泊）、瀑、桥、殿、阁、园、寨、沟、松等。",
             "- **边界**：①景区自身名（黄山/九寨沟/颐和园）不算 POI，它是“景区”层级；②通名（山峰、峡谷、寺庙、大殿）不算，除非作为专名一部分（西海大峡谷、诺日朗瀑布）；③周边景点（宏村、黄龙、川主寺）保留并标注，供实验6做景区外关联；④代词与简称（“那里”“大峡谷”单独出现）不算。",
             "- **易混淆情况**：西海（黄山景区，已收录）与北海公园（北京景点，停用词）区分；“诺日朗”单独出现泛指诺日朗一带，收录为 POI；“树正”是片名，收录树正寨/树正群海/树正沟而不收“树正”。",
             "- **示例**：五花海、光明顶、十七孔桥、树正寨、西海大峡谷。", "",
             "## 2. 交通方式", "",
             "- **定义**：文本中表达“从一处到另一处所乘坐/采用的手段”的名词性表达。",
             "- **边界**：①“乘车、坐车、下车、到达”是动作不是方式，不收；②索道站名（玉屏索道、云谷索道）是交通设施，归入本类并标注子类“索道缆车”，不作为 POI；③“步行30分钟”整体是时间+方式，步行作为交通方式实体、30分钟作为时间节点，分别记录。",
             "- **易混淆情况**：“大巴”单独出现与“景区大巴”都能指园内接驳，最长匹配优先；“自驾”既是方式也是动作，按方式收录。",
             "- **子类**：索道缆车 / 景区车辆 / 公共交通 / 长途交通 / 水上交通 / 自驾 / 步行 / 骑行。", "",
             "## 3. 时间节点", "",
             "- **定义**：表达游览安排中时间位置或持续时长的表达，含四类：时刻（7:30、上午9点）、时段（上午/中午/下午/全天）、时长（约30分钟、2个小时）、日期（Day1、第一天、10月1日）。",
             "- **边界**：①“早上早点出发”中的“早上”算时段；“早点”副词不算；②“3-5天买门票”中“3-5天”是提前量而非游览时长，仍按时长记录、由实验5在条件抽取时甄别；③“旺季/淡季”不算时间节点，归实验5条件类型。",
             "- **易混淆情况**：跨零点时间（17:00-17:35 晚间场次）按字面记录；“上午9点”整体记为时刻（含时段前缀），不再单独记“上午”。", "",
             "## 4. 识别方法概要", "",
             "- 分词：jieba + 自定义词典（entity_userdict.txt，POI 标注 nz、交通标注 n）；",
             "- POI/交通：自定义词典最长匹配扫描（长词优先、位置互斥），保证偏移量准确、避免“西海大峡谷”被切成“西海+大峡谷”；",
             "- 时间节点：正则规则（时钟范围→时刻→时长→时段的优先级链）；",
             "- 停用词：DOMAIN_STOPWORDS，根据第 1 轮词频可视化结果加入（见 iter_compare.json）。",
             "",
             f"词表规模：POI {len(merged)} 条，交通 {len(transport_entries)} 条，停用词 {len(DOMAIN_STOPWORDS)} 条。"]
    (OUT / "entity_schema.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"poi": len(merged), "transport": len(transport_entries),
                      "stopwords": len(DOMAIN_STOPWORDS), "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
