"""Verify public Ctrip travelogue candidates using urllib and lxml."""
import json
import re
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta
from lxml import html

CANDIDATES = [
    ('黄山','https://you.ctrip.com/travels/huangshan120061/3962261.html','后山上前山下，两日路线，明确上山和下山节点'),
    ('黄山','https://you.ctrip.com/travels/china110000/4078056.html','亲子两日，后山上前山下，云谷寺至光明顶'),
    ('黄山','https://you.ctrip.com/travels/huangshan19/4143838.html','亲子两日，DAY1和DAY2箭头式游览节点'),
    ('黄山','https://you.ctrip.com/travels/19/4038290.html','四天三晚，有逐日具体时间和节点'),
    ('黄山','https://you.ctrip.com/travels/huangshan120061/3110509.html','个人三日，云谷索道上山到慈光阁下山'),
    ('黄山','https://you.ctrip.com/travels/huangshan19/4154493.html','短篇一日，白鹤岭至光明顶至玉屏索道；可作短文本质量边界备选'),
    ('九寨沟','https://you.ctrip.com/travels/Jiuzhaigou25/4080314.html','独孤游记，金秋六天五晚，景区内游览叙述'),
    ('九寨沟','https://you.ctrip.com/travels/2032371/4137798.html','朋友两日，箭竹海熊猫海五花海珍珠滩等连续叙事'),
    ('九寨沟','https://you.ctrip.com/travels/Jiuzhaigou25/4023695.html','个人旅行经历，五花海珍珠滩长海五彩池'),
    ('九寨沟','https://you.ctrip.com/travels/guanghan1349/4148186.html','六日自由行中Day3九寨沟，三沟明确路线'),
    ('九寨沟','https://you.ctrip.com/travels/sichuan100009/4157757.html','四川多日游中DAY3，九寨沟完整游览路线'),
    ('九寨沟','https://you.ctrip.com/travels/sichuan100009/3963747.html','毕业旅行，早起购票至日则沟徒步及长海五彩池'),
    ('九寨沟','https://you.ctrip.com/travels/104/3992566.html','成都九寨沟六日，右线五花海到左线长海顺序'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4076390.html','夫妻四次游园，按四天列出路线；同系列其他篇不应重复纳入'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4162310.html','亲子游，北宫门至东宫门推荐并叙述实际返走到十七孔桥'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4126899.html','本地游客半日，北宫门苏州街谐趣园知春亭铜牛十七孔桥连续实际行程'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/3965467.html','同事游园与湖上泛舟，实际游览叙述，路线较弱'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4004412.html','开春游园，需核查实际路线是否足够'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4077504.html','汉服实游，西门至新建宫门明确路线；尾部含速8酒店推荐，应识别混合推广'),
    ('颐和园','https://you.ctrip.com/travels/beijing1/4112830.html','北京四天亲子特种兵，有颐和园实际行程，需检查路线密度'),
]

def fetch_one(item):
    scenic, url, note = item
    out = dict(scenic_spot=scenic,source='携程游记',url=url,route_features=note)
    try:
        req = urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=30) as response:
            raw=response.read()
            out['http_status']=response.status
            out['final_url']=response.url
        root=html.fromstring(raw)
        title=root.xpath('//h1/text()')
        out['title']=title[0].strip() if title else ''.join(root.xpath('//title/text()'))
        containers=root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-content-wrapper ") or contains(concat(" ",normalize-space(@class)," ")," rich-text-container ")]')
        out['body_readable']=bool(containers)
        body=containers[0] if containers else None
        text='\n'.join(t.strip() for t in body.itertext() if t.strip()) if body is not None else ''
        out['text_length']=len(text)
        dates=root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-date ") or contains(concat(" ",normalize-space(@class)," ")," text-xs ")]//text()')
        out['date_display']=' '.join(t.strip() for t in dates if re.search(r'20\d\d[.\-]\d',t))
        out['body_text']=text
        out['route_evidence_paragraphs']=[s for s in text.split('\n') if any(k in s for k in ('路线','DAY','Day','第一天','第二天','第三天','北宫门','往下','前往','→','——'))][:12]
        out['advertising_signals']=[k for k in ['巴士达','速8','预订','礼宾部','跟随博主'] if k in text]
        out['verified_at']=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    except Exception as exc:
        out.update(body_readable=False,error=str(exc))
    return out

if __name__=='__main__':
    result=[]
    p=Path(__file__).resolve().parents[1]/'data'/'crawl'/'ctrip_candidates.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    for c in CANDIDATES:
        item=fetch_one(c)
        result.append(item)
        p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(item['scenic_spot'],item.get('http_status'),item.get('text_length'),item.get('title'),flush=True)
        time.sleep(0.5)
