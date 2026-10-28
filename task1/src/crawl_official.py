"""重新采集已核实的全部官方来源及其全部原文路线分支。

不把同页分支伪装成多个来源。保留主题指南、历史版本、图片原件。
--offline 只重读本地快照；缺快照会失败，不编造成功。
"""
from __future__ import annotations
import argparse, importlib.util, json, hashlib, re, urllib.request, time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from lxml import html
from collect import extract

ROOT=Path(__file__).resolve().parents[1]

def load_base():
    spec=importlib.util.spec_from_file_location('official_specs',ROOT/'research/build_official_expansion.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),'utf-8')

def run(offline=False):
    base=load_base();base.run(offline)
    docs=json.loads((ROOT/'research/official_expansion.json').read_text('utf-8'))
    configurations=[
        dict(evidence_id='HS-O1',scenic_area='黄山',source_url='https://wap.huangshan.com.cn/detail/strategy/fjqlyzx',title='黄山风景区常见旅游咨询 一日游与二日游',published_at='2021-02-13',xpath='//div[contains(concat(" ",@class," ")," article-con ")]',kind='q20'),
        dict(evidence_id='HS-EXTRA1',scenic_area='黄山',source_url='https://www.ahsz.gov.cn/public/2655573/195153231.html',title='黄山冬季南北门一日及二日游推荐',published_at='2024-11-29',xpath='//*[contains(concat(" ",normalize-space(@class)," ")," j-fontContent ")]',kind='winter'),
        dict(evidence_id='HS-EXTRA2',scenic_area='黄山',source_url='https://wap.huangshan.com.cn/detail/strategy/122002',title='黄山及周边游玩攻略',published_at='2018-12-20',xpath='//*[@id="shareContent"]',kind='2018'),
    ]
    previous={r['evidence_id']:r for r in docs}
    for s in configurations:
        p=ROOT/'data/raw/pages'/f'{s["evidence_id"]}.html';p.parent.mkdir(parents=True,exist_ok=True)
        try:
            if not offline or not p.exists():
                if offline:
                    old={'HS-EXTRA1':'HS_EXTRA_OFFICIAL_1','HS-EXTRA2':'HS_EXTRA_OFFICIAL_2'}.get(s['evidence_id'])
                    oldp=ROOT/'data/raw/pages'/f'{old}.html'
                    if not old or not oldp.exists():raise FileNotFoundError(p)
                    p.write_bytes(oldp.read_bytes())
                else:
                    with urllib.request.urlopen(urllib.request.Request(s['source_url'],headers={'User-Agent':'Mozilla/5.0'}),timeout=35) as r:p.write_bytes(r.read())
            data=p.read_bytes();tree=html.fromstring(data);nodes=tree.xpath(s['xpath'])
            if not nodes:raise ValueError('官方正文选择器未命中')
            content=base.text_of('\n'.join(html.tostring(n,encoding='unicode') for n in nodes));variants=[]
            if s['kind']=='q20':
                content=base.text_of(extract(data.decode('utf-8'),{'extractor':'huangshan'})['raw_content'])
                one,two=re.split(r'[（(]2[）)]二日游路线[:：]',content,maxsplit=1)
                north,south=one.split('从北门上：',1)[1].split('从南门上：',1)
                for gate,part in [('北门',north),('南门',south)]:
                    for i,text in enumerate(re.split('[①②③]',part)[1:],1):variants.append(dict(title=f'{gate}一日游方案{i}',source_text=text.strip()))
                north,south=two.split('从北门上最佳线路：',1)[1].split('从南门上最佳线路：',1)
                variants.extend([dict(title='北门二日游',source_text=north),dict(title='南门二日游',source_text=south)])
            elif s['kind']=='winter':
                content=base.cut(content,'南门入线路推荐','齐云山景区')
                south,north=content.split('北门入线路推荐',1)
                for gate,part in [('南门',south),('北门',north)]:
                    one,two=part.split('一日游：',1)[1].split('二日游：',1)
                    variants.extend([dict(title=f'冬季{gate}一日游',source_text=one.strip()),dict(title=f'冬季{gate}二日游',source_text=two.strip())])
            else:
                # 原文第1–3天为黄山主体，第4天起为宏村/太平湖等周边。
                m=re.search(r'第[四4]天',content)
                main=content[:m.start()] if m else content
                variants=[dict(title='黄山主体山岳游 第1至3天',source_text=main.strip())]
            docs.append({**s,'raw_content':content,'raw_format':'text','collected_at':datetime.fromtimestamp(p.stat().st_mtime,ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),'snapshot_file':p.relative_to(ROOT).as_posix(),'snapshot_sha256':hashlib.sha256(data).hexdigest(),'route_variants':variants,'accepted':True,'include_in_main_dataset':True})
            print('OFFICIAL',s['evidence_id'],len(variants),flush=True)
        except Exception as e:docs.append({**s,'accepted':False,'error':str(e)});print('FAIL',s['evidence_id'],str(e),flush=True)
        if not offline:time.sleep(1)
    routes=[]
    for d in docs:
        if not d.get('accepted'):continue
        for i,v in enumerate(d.get('route_variants',[]),1):routes.append(dict(route_id=f'{d["evidence_id"]}-R{i}',source_record_id=d['evidence_id'],scenic_area=d['scenic_area'],source_url=d['source_url'],title=v['title'],raw_content=v['source_text'],ordered_route=bool(d.get('include_in_main_dataset')),published_at=d.get('published_at','')))
    write_jsonl(ROOT/'data/raw/official_documents.jsonl',docs);write_jsonl(ROOT/'data/raw/official_routes.jsonl',routes)
    summary={'documents':len(docs),'accepted_documents':sum(d.get('accepted',False) for d in docs),'ordered_route_variants':sum(r['ordered_route'] for r in routes),'supplementary_theme_variants':sum(not r['ordered_route'] for r in routes),'failures':[{'id':d['evidence_id'],'error':d.get('error')} for d in docs if not d.get('accepted')]}
    (ROOT/'research/official_collection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8');print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');run(p.parse_args().offline)
