"""将已核验的网页/浏览器快照合并；一篇文档一条记录，另列官方路线分支。

先运行 collect.py --offline、research/build_official_expansion.py --offline。
本脚本不请求网络，不把搜索摘要或自写路线当成原始数据。
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from collect import ROOT, extract
from preprocess import clean_text

def readj(path):
    return json.loads(path.read_text('utf-8')) if path.exists() else []

def canonical(url):
    p=urlsplit(url)
    # 同一携程文档可有不同城市前缀，文章ID才是稳定标识。
    if p.netloc.endswith('ctrip.com') and '/travels/' in p.path:
        return 'ctrip:' + p.path.rsplit('/',1)[-1]
    return urlunsplit((p.scheme,p.netloc,p.path.rstrip('/'),'',''))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    raw=ROOT/'data/raw'; by_url={}; audit=[]; routes=[]
    for source in readj(ROOT/'sources.json'):
        path=ROOT/source['raw_file']
        try:
            r={**{k:v for k,v in source.items() if k!='extractor'},**extract(path.read_text('utf-8'),source),
                'snapshot_sha256':sha(path),'acquisition_method':'urllib.request + lxml XPath',
                'collected_at':source['collected_at']}
            by_url[canonical(r['source_url'])]=r
        except Exception as e:
            audit.append({'record_id':source['record_id'],'status':'seed_extract_failed','error':str(e)})
    # 扩展官方正文已经由专用XPath与明确边界从保留网页提取。
    for s in readj(ROOT/'research/official_expansion.json'):
        if not s.get('include_in_main_dataset') or not s.get('accepted'):continue
        path=ROOT/s['snapshot_file']
        if sha(path)!=s['snapshot_sha256']: raise ValueError('官方快照hash不匹配 '+str(path))
        key=canonical(s['source_url']);old=by_url.get(key)
        rid=old['record_id'] if old else s['evidence_id']
        r=dict(record_id=rid,scenic_area=s['scenic_area'],source_platform='官方' if 'jiuzhai.com' in s['source_url'] or 'summerpalace.net.cn' in s['source_url'] or '.gov.cn/' in s['source_url'] else '官方推荐转载',source_url=s['source_url'],title=s['title'],text_type='official_route',collected_at=s['collected_at'],raw_content=s['raw_content'],raw_format='text',extraction_selector=s.get('xpath',s.get('extraction_selector',''))+'; text_start='+s.get('text_start','')+'; text_end='+s.get('text_end',''),raw_file=s['snapshot_file'],content_scope='official_target_scenic_route_sections',author='',published_at=s['published_at'],provenance_note=s['provenance_note'],snapshot_sha256=s['snapshot_sha256'],acquisition_method=('官方图片目视转录并核验' if s['extractor']=='official_image_visual_transcription' else 'urllib.request + lxml XPath + 明确原文边界'),date_note='来源页面显示日期；历史文本不作为当前开放和票务承诺')
        by_url[key]=r
        for i,v in enumerate(s.get('route_variants',[]),1):
            if v.get('counts_as_scenic_internal_route') is False:continue
            routes.append(dict(route_id=f'{rid}-R{i}',source_record_id=rid,scenic_area=r['scenic_area'],source_url=r['source_url'],route_title=v['title'],route_text=v['source_text'],published_at=r['published_at'],scope_note=s['provenance_note']))
    # 黄山额外官方来源，已区分主体山岳游与周边延伸。
    for i,s in enumerate(readj(ROOT/'research/huangshan_extra_official.json'),1):
        path=ROOT/s['raw_file'];rid=f'HS-EXTRA{i}'
        if s.get('snapshot_sha256') and sha(path)!=s['snapshot_sha256']: raise ValueError('黄山快照hash不匹配')
        variants=[v for v in s.get('route_variants',[]) if v.get('counts_as_scenic_internal_route',True)]
        body='\n\n'.join(v['source_text'] for v in variants)
        if not body:continue
        r=dict(record_id=rid,scenic_area='黄山',source_platform='官方' if 'huangshan.com.cn' in s['url'] else '官方推荐转载',source_url=s['url'],title=s['title'],text_type='official_route',collected_at=s['collected_at'],raw_content=body,raw_format='text',extraction_selector=s['xpath']+'; 仅黄山主体路线原文分支',raw_file=s['raw_file'],content_scope='official_huangshan_route_section',author='',published_at=s['published_at'].split(' ')[0],provenance_note=s['official_basis']+'；'+s.get('scope_note',''),snapshot_sha256=sha(path),acquisition_method='urllib.request + lxml XPath',date_note='页面显示日期')
        by_url[canonical(r['source_url'])]=r
        for j,v in enumerate(variants,1):
            routes.append(dict(route_id=f'{rid}-R{j}',source_record_id=rid,scenic_area='黄山',source_url=r['source_url'],route_title=v['title'],route_text=v['source_text'],published_at=r['published_at'],scope_note=s.get('scope_note','')))
    # 原黄山第20问按真实北/南门一日3分支和二日方案整理8条原文。
    hs=next((r for r in by_url.values() if r['record_id']=='HS-O1'),None)
    if hs:
        text=clean_text(hs['raw_content'],hs['raw_format'])[0]
        oneday,twoday=text.split('(2)二日游路线:',1)
        for gate,part in [('北门',oneday.split('从北门上:',1)[1].split('从南门上:',1)[0]),('南门',oneday.split('从南门上:',1)[1])]:
            blocks=re.split(r'[①②③]',part)[1:]
            for j,block in enumerate(blocks,1):
                routes.append(dict(route_id=f'HS-O1-{gate}-D1-{j}',source_record_id='HS-O1',scenic_area='黄山',source_url=hs['source_url'],route_title=f'{gate}一日游方案{j}',route_text=block.strip(),published_at=hs['published_at'],scope_note='2021年清明历史指南 原文分支 未生成新路线'))
        for gate,part in [('北门',twoday.split('从北门上最佳线路:',1)[1].split('从南门上最佳线路:',1)[0]),('南门',twoday.split('从南门上最佳线路:',1)[1])]:
            routes.append(dict(route_id=f'HS-O1-{gate}-D2',source_record_id='HS-O1',scenic_area='黄山',source_url=hs['source_url'],route_title=f'{gate}二日游',route_text=part.strip(),published_at=hs['published_at'],scope_note='2021年清明历史指南 原文分支 未生成新路线'))
    for s in readj(ROOT/'research/ctrip_expansion_sources.json'):
        key=canonical(s['source_url'])
        if key in by_url:continue
        p=ROOT/s['raw_file']
        try:
            r={**{k:v for k,v in s.items() if k!='extractor'},**extract(p.read_text('utf-8'),s),'snapshot_sha256':sha(p),'acquisition_method':'公开目录发现 + urllib.request + lxml XPath'}
            # 多城游记保留全文时明确范围，后续抽取须按目标景区限定。
            r['content_scope']='article_body_may_include_other_destinations'
            by_url[key]=r
        except Exception as e:audit.append({'record_id':s['record_id'],'status':'ctrip_extract_failed','error':str(e)})
    for r in readj(raw/'xiaohongshu.json'):
        key=canonical(r['source_url'])
        if key in by_url: audit.append({'record_id':r['record_id'],'status':'duplicate_source_url'})
        else:by_url[key]=r
    records=list(by_url.values())
    # 路线原文精确去重；不同发布日期或不同条件保留为不同版本，但标注近似。
    seen={};unique=[];route_duplicates=[]
    for r in routes:
        fp=re.sub(r'\s+','',clean_text(r['route_text'],'text')[0])
        key=(r['scenic_area'],fp)
        if key in seen:route_duplicates.append({'route_id':r['route_id'],'duplicate_of':seen[key]})
        else:seen[key]=r['route_id'];unique.append(r)
    (raw/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),'utf-8')
    processed=ROOT/'data/processed';processed.mkdir(exist_ok=True)
    (processed/'official_routes.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in unique),'utf-8')
    if unique:
        with (processed/'official_routes.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(unique[0]));w.writeheader();w.writerows(unique)
    (raw/'assembly_audit.json').write_text(json.dumps({'documents':len(records),'official_route_variants':len(unique),'route_exact_duplicates':route_duplicates,'issues':audit},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'documents':len(records),'official_route_variants':len(unique),'issues':len(audit)},ensure_ascii=False))

if __name__=='__main__':main()
