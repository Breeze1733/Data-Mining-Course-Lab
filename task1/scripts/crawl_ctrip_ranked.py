"""Filter 携程 travelogues by public read count; re-runs reuse the cache, and hot directories are discovered automatically on the first run.

python src/crawl_ctrip_ranked.py --area all --pool-size 40 --max-pages 120
This script does not invoke data cleaning or Word/Excel export.
"""
from __future__ import annotations
import argparse, json, re, hashlib
from pathlib import Path
from urllib.parse import urljoin
from collections import Counter
from lxml import html
import expand_ctrip as base

ROOT=base.ROOT
OUT=ROOT/'data/crawl/ctrip_ranked_candidates.json'

def number(text):
    m=re.search(r'(\d+(?:\.\d+)?)\s*(万|千|[wWkK])?',str(text).replace(',',''))
    return round(float(m[1])*{'万':10000,'千':1000,'w':10000,'W':10000,'k':1000,'K':1000}.get(m[2],1)) if m else None

def metrics(raw):
    t=html.fromstring(raw)
    ends=t.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travels_end ")]')
    text=' '.join(x.text_content() for x in ends) if ends else t.text_content()
    m=re.search(r'阅读量\s*([\d.,]+\s*(?:万|千|[wkWK])?)',text)
    return {'read_count_display':m[1].strip() if m else '', 'read_count':number(m[1]) if m else None,'read_count_source':'article_public_read_count' if m else 'not_exposed'}

def dump(rows,logs):
    base.save(OUT,list(rows.values()))
    base.save(ROOT/'data/crawl/ctrip_ranked_log.json',logs)

def store_article(meta,rows,refresh=False):
    meta={k:v for k,v in meta.items() if k!='error'}
    r=base.verify_one(meta,refresh=refresh)
    if r.get('raw_file') and (ROOT/r['raw_file']).exists():r.update(metrics((ROOT/r['raw_file']).read_bytes()))
    if r.get('read_count') is None and meta.get('read_count') is not None:
        r.update(read_count=meta['read_count'],read_count_display=meta.get('read_count_display',''),read_count_source='public_directory_浏览')
    r['read_count_observed_at']=r['collected_at'];rows[r['record_id']]=r
    return r

def run(area='all',pool_size=40,max_pages=120,offline=False,retry_failed=False):
    rows={}
    if OUT.exists():rows={r['record_id']:r for r in json.loads(OUT.read_text('utf-8'))}
    # Directories/articles actually fetched in the first round are reused directly; article bodies are not requested twice.
    for p in [ROOT/'data/crawl/ctrip_expansion.json']:
        if p.exists():
            for r in json.loads(p.read_text('utf-8')):
                if r.get('raw_file') and (ROOT/r['raw_file']).exists():
                    r={**r,**metrics((ROOT/r['raw_file']).read_bytes())}
                    rows.setdefault(r['record_id'],r)
    logpath=ROOT/'data/crawl/ctrip_ranked_log.json'
    logs=json.loads(logpath.read_text('utf-8')) if logpath.exists() else []
    if retry_failed and not offline:
        for old in list(rows.values()):
            if old.get('error') and area in ('all',old['scenic_area']):
                # Retry only request/extraction failures; quality rejections of valid bodies are not relaxed by re-running.
                store_article(old,rows,refresh=True);dump(rows,logs)
    # The fixed public seeds also serve as a candidate discovery entry point, so a fresh clone does not depend on the historical JSON cache.
    if not offline and area in ('all','颐和园'):
        for url in base.BEIJING_SEEDS:
            rid='CTRIP_'+base.article_id(url)
            if rid not in rows:
                store_article(dict(scenic_area='颐和园',url=url,title='',author='',discovery_method='curated_public_seed'),rows)
                dump(rows,logs)
    for spot,slug in [('黄山','huangshan19'),('九寨沟','jiuzhaigou25'),('颐和园','beijing1')]:
        if area not in ('all',spot):continue
        pool=lambda:[r for r in rows.values() if r.get('scenic_area')==spot and r.get('accepted') and r.get('read_count') is not None]
        # Hot lists are a discovery entry point; final ranking still uses the public
        # read count values. The two smaller directories are walked in full; the
        # Beijing citywide directory uses an explicit page bound, so “hot” must not
        # be mislabeled as read-count ordering.
        page_limit=min(max_pages,{'黄山':15,'九寨沟':38,'颐和园':120}[spot])
        for page in range(1,page_limit+1):
            if offline:break
            url=f'https://you.ctrip.com/travels/{slug}' if page==1 else f'https://you.ctrip.com/travels/{slug}/t3-p{page}'
            try:
                status,final,data=base.get(url);t=html.fromstring(data)
                if '验证' in ''.join(t.xpath('//title/text()')):raise ValueError('返回验证页，停止该目录')
                cards=t.xpath('//a[.//h2]')
                catalog=ROOT/'data/raw/catalogs'/f'{slug}_hot_{page}.html'
                catalog.parent.mkdir(parents=True,exist_ok=True);catalog.write_bytes(data)
                logs.append({'kind':'directory','area':spot,'url':url,'http_status':status,'cards':len(cards),'time':base.stamp()})
                if not cards:break
                metas=[]
                for c in cards:
                    link=urljoin('https://you.ctrip.com',c.get('href','')).replace('http://','https://');m=re.search(r'/(\d+)\.html',link)
                    if not m:continue
                    rid='CTRIP_'+m[1];title=''.join(c.xpath('.//h2//text()')).strip()
                    if base.PROMO_TITLE.search(title):continue
                    summary=' '.join(c.xpath('.//p//text()'))
                    # The Beijing directory includes citywide content; verify only targeted titles or general trip reports that may cover 颐和园.
                    if spot=='颐和园' and not re.search(r'颐和园|北京|京城|帝都|四九城|北平',title+' '+summary):continue
                    text=c.text_content();before=text.split('发表于',1)[0];author=before[len(title):].strip() if before.startswith(title) else ''
                    read=''.join(c.xpath('.//*[@title="浏览"]//text()')).strip()
                    if rid in rows:
                        if read:rows[rid].update(directory_read_count_display=read,directory_read_count=number(read))
                        continue
                    metas.append(dict(scenic_area=spot,title=title,url=link,author=author[:50],summary=summary,directory_url=url,read_count_display=read,read_count=number(read)))
                # Card read counts are explicitly labeled; verify the highest-read-count bodies first.
                metas.sort(key=lambda x:x['read_count'] if x['read_count'] is not None else -1,reverse=True)
                for meta in metas:
                    # Once the verified pool is large enough, only new bodies that could
                    # enter the top 25 by read count are requested.
                    # This is labeled as in-range sampling; the site is not claimed to
                    # offer a site-wide read-count ranking API.
                    reads=sorted((r['read_count'] for r in pool()),reverse=True)
                    if len(reads)>=pool_size and meta.get('read_count') is not None and meta['read_count']<reads[pool_size-1]:continue
                    store_article(meta,rows);dump(rows,logs)
                print(spot,'page',page,'eligible_pool',len(pool()),flush=True)
                dump(rows,logs)
            except Exception as e:
                logs.append({'kind':'directory_failure','area':spot,'url':url,'error':str(e),'time':base.stamp()});dump(rows,logs);print('FAIL',url,str(e),flush=True);break
        print('AREA',spot,'eligible',len(pool()),flush=True)
    dump(rows,logs)
    print(json.dumps({'accepted_by_area':dict(Counter(r['scenic_area'] for r in rows.values() if r.get('accepted'))),'candidates':len(rows)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--area',choices=['all','黄山','九寨沟','颐和园'],default='all');p.add_argument('--pool-size',type=int,default=40);p.add_argument('--max-pages',type=int,default=120);p.add_argument('--offline',action='store_true');p.add_argument('--retry-failed',action='store_true');a=p.parse_args()
    if a.pool_size<25:p.error('--pool-size must be at least 25')
    if a.max_pages<1:p.error('--max-pages must be positive')
    run(a.area,a.pool_size,a.max_pages,a.offline,a.retry_failed)
