"""低频采集官方路线与携程公开游记；正文缺失时拒绝当作成功。

python src/collect.py --offline  从保留的网页快照重新生成 records.jsonl
python src/collect.py            按 sources.json 重新抓取（不绕过验证）
小红书由已登录浏览器 DOM 导出到 data/raw/xiaohongshu.json，再统一合并。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from lxml import html

ROOT = Path(__file__).resolve().parents[1]

def stamp():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def fragment(nodes):
    return '\n'.join(html.tostring(n, encoding='unicode', with_tail=False) for n in nodes)

def extract(page: str, source: dict):
    t = html.fromstring(page)
    kind = source['extractor']
    title = ''.join(t.xpath('//title/text()')).strip()
    author = ''
    published = source.get('published_at', '')
    if kind == 'ctrip':
        nodes = t.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," travel-content-wrapper ")]')
        if not nodes:
            nodes = t.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," rich-text-container ")]')
        if not nodes or '验证' in title:
            raise ValueError('携程正文缺失或返回验证页面，未计入数据集')
        nodes = [nodes[0]]
        for noise in nodes[0].xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," journal_detail ") or contains(concat(" ",normalize-space(@class)," ")," travels_end ")]'):
            noise.drop_tree()
        authors = t.xpath('//*[contains(@class,"author") and not(ancestor::script)]')
        author = next((x.text_content().strip() for x in authors if 0 < len(x.text_content().strip()) < 60), '')
        date = re.search(r'(?:发表于|发布于|更新于)\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})', t.text_content())
        if date: published = date[1].replace('/', '-').replace('.', '-')
        selector = 'travel-content-wrapper | rich-text-container （首个正文容器）'
        # 多目的地游记按已核验的段落边界截取；完整网页仍保留在 pages/。
        if source.get('section_start'):
            selected, active = [], False
            for child in nodes[0]:
                txt = re.sub(r'\s+', ' ', child.text_content()).strip()
                if (not source.get('section_start_tag') or child.tag == source['section_start_tag']) and re.search(source['section_start'], txt): active = True
                if active and source.get('section_end') and re.search(source['section_end'], txt): break
                if active: selected.append(child)
            nodes = selected
            selector += '; section_start=' + source['section_start'] + '; section_end=' + source.get('section_end','EOF')
    elif kind == 'huangshan':
        # 直接渲染的正文与内嵌 JSON 重复，只取第一个正文内第20问。
        content = t.xpath('//div[contains(concat(" ",@class," ")," article-con ")]')[0]
        paras = content.xpath('./p')
        nodes, active = [], False
        for p in paras:
            txt = p.text_content().strip()
            if txt.startswith('20.'): active = True
            if active and re.match(r'21[.．、]', txt): break
            if active: nodes.append(p)
        title = '黄山风景区常见旅游咨询 一日游与二日游线路'
        selector = 'div.article-con > p，第20问至第21问之前'
    elif kind == 'jiuzhai':
        nodes = t.xpath('//*[@id="imagegrid-8941-particle"]//*[contains(@class,"g-imagegrid-desc")]')
        title = '九寨沟景区官方网站 游玩方式 一日精华游'
        selector = '#imagegrid-8941-particle .g-imagegrid-desc'
    elif kind == 'summer_palace':
        nodes = [p for p in t.xpath('//div[contains(@class,"TRS_UEDITOR")]//p') if p.text_content().strip().startswith(('颐和园西门→','颐和园东宫门→'))]
        title = '北京市属公园暑期红色游 颐和园推荐路线'
        selector = 'div.TRS_UEDITOR 内以颐和园西门或东宫门开头的两个p'
    else:
        raise ValueError('未知提取器 ' + kind)
    if not nodes or len(''.join(x.text_content() for x in nodes).strip()) < 80:
        raise ValueError('正文提取为空或过短')
    return dict(title=source.get('expected_title',title), author=author, published_at=published,
                extraction_selector=selector, raw_content=fragment(nodes), raw_format='html')

def run(offline=False):
    sources = json.loads((ROOT/'sources.json').read_text('utf-8'))
    raw_dir = ROOT/'data/raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    records, logs = [], []
    for s in sources:
        path = ROOT/s['raw_file']
        try:
            if offline:
                data = path.read_bytes()
                fetched = s.get('collected_at', '')
                if not fetched: raise ValueError('离线快照缺少真实采集时间')
                status = 'offline_snapshot'
            else:
                req = urllib.request.Request(s['source_url'], headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=35) as resp:
                    data = resp.read()
                    status = resp.status
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                fetched = stamp()
                s['collected_at'] = fetched
            values = extract(data.decode('utf-8', errors='strict'), s)
            records.append({**{k:v for k,v in s.items() if k!='extractor'}, **values,
                'collected_at':fetched, 'acquisition_method':'urllib.request + lxml XPath',
                'content_scope':s.get('content_scope','article_body'),
                'snapshot_sha256':hashlib.sha256(data).hexdigest()})
            logs.append({'record_id':s['record_id'],'url':s['source_url'],'status':status,'accepted':True,'bytes':len(data),'time':fetched})
            print('OK',s['record_id'],len(values['raw_content']),values['title'][:45],flush=True)
        except Exception as e:
            logs.append({'record_id':s['record_id'],'url':s['source_url'],'accepted':False,'error':str(e),'time':stamp()})
            print('FAIL',s['record_id'],str(e),flush=True)
        if not offline: time.sleep(1.0)
    xhs = raw_dir/'xiaohongshu.json'
    if xhs.exists():
        records.extend(json.loads(xhs.read_text('utf-8')))
    (raw_dir/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    (raw_dir/'collection_log.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')
    if not offline:
        (ROOT/'sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8')
    print('records',len(records),'failures',sum(not x['accepted'] for x in logs))

if __name__ == '__main__':
    a=argparse.ArgumentParser(); a.add_argument('--offline',action='store_true')
    run(a.parse_args().offline)
