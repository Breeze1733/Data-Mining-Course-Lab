"""Aggregate collection results only: body completeness, source provenance, deduplication, and per-platform popularity-based selection.

python src/select_collection.py --per-platform 25
Does not overwrite legacy preprocessing outputs; performs no tokenization, entity extraction, or route inference.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from lxml import html
import expand_ctrip as base

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/collected'
AREAS = ('黄山', '九寨沟', '颐和园')
PROMO = re.compile(r'加我微信|添加微信|微信号|联系.{0,8}微信|包车电话|私人订制|报名咨询')
ROUTE = re.compile(r'路线|线路|行程|游览|徒步|步行|入园|出园|乘车|下车|先|然后|之后|→|➡|—')

def read_json(path, default=None):
    return json.loads(path.read_text('utf-8')) if path.exists() else default

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text('utf-8').splitlines() if line.strip()] if path.exists() else []

def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), 'utf-8')

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def canonical(url):
    return url.split('?')[0].replace('/search_result/', '/explore/').rstrip('/')

def ctrip_candidates():
    rows, audit = [], []
    for r in read_json(ROOT/'data/crawl/ctrip_ranked_candidates.json', []):
        if not r.get('accepted'):
            audit.append(dict(scenic_area=r['scenic_area'], platform='携程', url=r.get('url',''),
                              accepted=False, reasons=r.get('rejection_reasons', ['crawler_rejected'])))
            continue
        try:
            data = (ROOT/r['raw_file']).read_bytes()
            if hashlib.sha256(data).hexdigest() != r['snapshot_sha256']:
                raise ValueError('snapshot_hash_mismatch')
            tree = html.fromstring(data)
            parts, selector = base.body_parts(tree)
            text = '\n'.join(parts)
            containers = tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-content-wrapper ") or contains(concat(" ",normalize-space(@class)," ")," rich-text-container ")]')
            raw_html = html.tostring(containers[0], encoding='unicode') if containers else ''
            if len(text.strip()) < 80 or not raw_html:
                raise ValueError('missing_article_body')
            if r.get('read_count') is None:
                raise ValueError('missing_read_count')
            rows.append(dict(record_id=r['record_id'], scenic_area=r['scenic_area'],
                source_platform='携程', text_type='游客游记', source_url=r['url'],
                title=r['title'], author=r.get('author',''), published_at=r.get('published_at',''),
                collected_at=r.get('collected_at',''), raw_content=raw_html, raw_format='html',
                body_text=text, body_sha256=digest(text), snapshot_file=r['raw_file'],
                snapshot_sha256=r['snapshot_sha256'], extraction_selector=selector,
                read_count=r['read_count'], read_count_display=r.get('read_count_display',''),
                metric_observed_at=r.get('read_count_observed_at',r.get('collected_at','')),
                metric_source=r.get('read_count_source',''), metric_precision='displayed_rounded',
                matched_pois=r.get('matched_pois',[]), route_evidence=r.get('route_evidence',[]),
                selection_scope='已实际采集并通过路线检查的携程候选池；非全站穷尽排名'))
        except Exception as e:
            audit.append(dict(scenic_area=r['scenic_area'], platform='携程', url=r.get('url',''),
                              accepted=False, reasons=[str(e)]))
    return rows, audit

def xhs_candidates():
    rows, audit = [], []
    for r in read_json(ROOT/'data/raw/xiaohongshu_browser_export.json', []):
        area, text = r['scenic_area'], r.get('raw_content','')
        pois = [p for p in base.NODES[area] if p in text]
        reasons = []
        if len(re.sub(r'\s','',text)) < 80: reasons.append('body_too_short')
        if len(pois) < 2 or not ROUTE.search(text): reasons.append('insufficient_route_text')
        if PROMO.search(text): reasons.append('solicitation_in_body')
        if r.get('like_count') is None: reasons.append('missing_like_count')
        url = canonical(r['source_url'])
        if not re.search(r'/explore/[0-9a-f]+$', url): reasons.append('unexpected_note_url')
        audit.append(dict(scenic_area=area, platform='小红书', url=url, accepted=not reasons, reasons=reasons))
        if reasons: continue
        record_id = 'XHS_'+url.rsplit('/',1)[-1]
        snap = ROOT/'data/raw/notes'/f'{record_id}.json'
        snap.parent.mkdir(parents=True, exist_ok=True)
        # Freeze the real text from the browser export here; cookies, comments, and AI search summaries are not saved.
        snap.write_text(json.dumps({**r,'source_url':url},ensure_ascii=False,indent=2), 'utf-8')
        rows.append(dict(record_id=record_id, scenic_area=area, source_platform='小红书',
            text_type='游客游记', source_url=url, source_url_with_token=r.get('source_url_with_token',''), title=r.get('title',''), author=r.get('author',''),
            published_at_raw=r.get('published_at_raw',''), collected_at=r['collected_at'],
            raw_content=text, raw_format='text', body_text=text, body_sha256=digest(text),
            snapshot_file=snap.relative_to(ROOT).as_posix(), snapshot_sha256=hashlib.sha256(snap.read_bytes()).hexdigest(),
            like_count=r['like_count'], like_count_display=r.get('like_count_display',''),
            metric_observed_at=r.get('like_count_observed_at',r['collected_at']),
            metric_source=r.get('like_count_source',''), metric_precision='displayed_rounded',
            search_keyword=r.get('search_keyword',''), search_sort=r.get('search_sort',''),
            extraction_selector=r.get('extraction_selector','#detail-desc.innerText'), matched_pois=pois,
            selection_scope='各景区 游记 路线 搜索、最多点赞排序下实际可访问的含路线正文；图片未OCR'))
    return rows, audit

def select(rows, metric, limit):
    result, duplicates = [], []
    for area in AREAS:
        seen_urls, seen_text = set(), set()
        eligible = sorted((r for r in rows if r['scenic_area']==area),
                          key=lambda r: (-(r[metric]), r['source_url']))
        for r in eligible:
            url = canonical(r['source_url'])
            h = digest(re.sub(r'\s+', '', r['body_text']))
            if url in seen_urls or h in seen_text:
                duplicates.append(dict(record_id=r['record_id'], scenic_area=area, reason='duplicate_url_or_body'))
                continue
            seen_urls.add(url); seen_text.add(h)
            if sum(x['scenic_area']==area for x in result) < limit:
                result.append({**r, 'rank_within_scenic_platform':sum(x['scenic_area']==area for x in result)+1,
                               'rank_metric':metric})
    return result, duplicates

def write_csv(path, rows):
    fields = ['record_id','scenic_area','source_platform','text_type','rank_within_scenic_platform',
              'rank_metric','read_count','read_count_display','like_count','like_count_display',
              'title','author','published_at','published_at_raw','collected_at','metric_observed_at',
              'source_url','source_url_with_token','snapshot_file','snapshot_sha256','raw_format','raw_content','body_text',
              'search_keyword','search_sort','selection_scope']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for r in rows:
            # HTML contains many image tags and is unsuitable for Excel cells; the CSV
            # keeps the full readable body text, while the untouched HTML original
            # remains in the JSONL and snapshot_file.
            r={**r,'raw_content':r['body_text'],'raw_format':'text'}
            # Prevent web-sourced text from being executed as formulas by spreadsheet software; the JSONL keeps the original without this escaping.
            writer.writerow({k:("'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in r.items()})

def run(per_platform=25):
    OUT.mkdir(parents=True, exist_ok=True)
    ctrip, ca = ctrip_candidates(); xhs, xa = xhs_candidates()
    cs, cd = select(ctrip,'read_count',per_platform)
    xs, xd = select(xhs,'like_count',per_platform)
    tourists = cs+xs
    docs = read_jsonl(ROOT/'data/raw/official_documents.jsonl')
    routes = read_jsonl(ROOT/'data/raw/official_routes.jsonl')
    write_jsonl(OUT/'tourist_routes.jsonl',tourists)
    write_csv(OUT/'tourist_routes.csv',tourists)
    selected_ids={(r['scenic_area'],r['record_id']) for r in tourists}
    pool_fields=['record_id','scenic_area','source_platform','title','read_count','read_count_display','like_count','like_count_display','selected','source_url','source_url_with_token']
    with (OUT/'eligible_candidate_pool.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=pool_fields,extrasaction='ignore');w.writeheader()
        for r in ctrip+xhs:
            entry={**{k:r.get(k,'') for k in pool_fields},'selected':(r['scenic_area'],r['record_id']) in selected_ids}
            w.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in entry.items()})
    write_jsonl(OUT/'official_documents.jsonl',docs)
    write_jsonl(OUT/'official_routes.jsonl',routes)
    write_jsonl(OUT/'candidate_audit.jsonl',ca+xa)
    for area in AREAS:
        for label, arr in [('ctrip',cs),('xiaohongshu',xs)]:
            write_jsonl(OUT/area/f'{label}_top{per_platform}.jsonl',[r for r in arr if r['scenic_area']==area])
    counts=[]
    for area in AREAS:
        for platform, arr, pool in [('携程',cs,ctrip),('小红书',xs,xhs)]:
            count=sum(r['scenic_area']==area for r in arr)
            counts.append(dict(scenic_area=area,platform=platform,eligible_candidates=sum(r['scenic_area']==area for r in pool),
                               selected=count,target=per_platform,shortfall=max(0,per_platform-count)))
    snapshot_errors=[]
    for r in tourists:
        p=ROOT/r['snapshot_file']
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=r['snapshot_sha256']:
            snapshot_errors.append(r['record_id'])
    for d in docs:
        if d.get('accepted'):
            p=ROOT/d['snapshot_file']
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=d['snapshot_sha256']:
                snapshot_errors.append(d['evidence_id'])
    required=('record_id','scenic_area','source_platform','text_type','source_url','title','raw_content','collected_at','snapshot_file')
    missing_required=[{'record_id':r['record_id'],'fields':[f for f in required if not r.get(f)]} for r in tourists if any(not r.get(f) for f in required)]
    ordered_counts=Counter(r['scenic_area'] for r in routes if r['ordered_route'])
    missing_official=[area for area in AREAS if not ordered_counts[area]]
    summary=dict(generated_at=base.stamp(),stage='data_collection_only',counts=counts,
        tourist_records=len(tourists),official_documents=len(docs),official_accepted=sum(bool(d.get('accepted')) for d in docs),
        official_ordered_route_variants=dict(ordered_counts),
        official_theme_variants=dict(Counter(r['scenic_area'] for r in routes if not r['ordered_route'])),
        duplicate_exclusions=cd+xd,snapshot_errors=snapshot_errors,missing_required=missing_required,missing_official=missing_official,
        metadata_missing={'author':sum(not r.get('author') for r in tourists),
                          'publication_date':sum(not (r.get('published_at') or r.get('published_at_raw')) for r in tourists)})
    summary['complete']=all(r['shortfall']==0 for r in counts) and not snapshot_errors and not missing_required and not missing_official and len(docs)>0 and all(d.get('accepted') for d in docs)
    (OUT/'collection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if summary['complete'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--per-platform',type=int,default=25);a=p.parse_args()
    if a.per_platform<1:p.error('--per-platform must be positive')
    raise SystemExit(run(a.per_platform))
