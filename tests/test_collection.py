"""采集入口的冷启动和断点行为回归检查，不访问真实网站。"""
import sys as _sys
from pathlib import Path as _P
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import crawl_ctrip_ranked as ctrip
import crawl_official as official
import expand_ctrip as base


class Response(BytesIO):
    status = 200


class CollectionEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'data'/'crawl').mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def test_missing_offline_snapshots_never_trigger_network(self):
        builder = official.load_base()
        with patch.object(official, 'ROOT', self.root), \
             patch.object(official, 'load_base', return_value=builder), \
             patch.object(builder, 'ROOT', self.root), \
             patch.object(builder, 'HERE', self.root/'data'/'crawl'), \
             patch.object(builder, 'PAGES', self.root/'data'/'crawl'/'official_expansion_pages'), \
             patch('urllib.request.urlopen') as request, redirect_stdout(StringIO()):
            official.run(offline=True)
        request.assert_not_called()
        report = json.loads((self.root/'data'/'crawl'/'official_collection_summary.json').read_text('utf-8'))
        self.assertEqual(report['accepted_documents'], 0)
        self.assertEqual(len(report['failures']), len(builder.SOURCES)+4)

    def test_official_sources_bootstrap_without_a_prior_manifest(self):
        builder = official.load_base()
        source = builder.S('TEST', '九寨沟', 'https://example.org/route', '测试路线', '', '//*[@id="body"]',
                           variants=[('测试方案', '', '')])
        fixture = '<html><div id="body">长海→五彩池→诺日朗</div></html>'.encode()
        with patch.object(builder, 'ROOT', self.root), \
             patch.object(builder, 'HERE', self.root/'data'/'crawl'), \
             patch.object(builder, 'PAGES', self.root/'data'/'crawl'/'official_expansion_pages'), \
             patch.object(builder, 'SOURCES', [source]), \
             patch('urllib.request.urlopen', side_effect=lambda *a, **k: Response(fixture)) as request, \
             patch.object(builder.time, 'sleep'), redirect_stdout(StringIO()):
            builder.run(offline=False)
        rows = json.loads((self.root/'data'/'crawl'/'official_expansion.json').read_text('utf-8'))
        self.assertTrue(all(r['accepted'] for r in rows))
        self.assertEqual(request.call_count, 2)  # HTML与官方图片原件
        self.assertTrue((self.root/rows[0]['snapshot_file']).is_file())

    def test_ctrip_seeds_bootstrap_without_cached_candidate_json(self):
        def verify(meta, refresh=False):
            return {**meta, 'record_id':'CTRIP_'+base.article_id(meta['url']),
                    'collected_at':base.stamp(), 'accepted':False}
        with patch.object(ctrip, 'ROOT', self.root), \
             patch.object(ctrip, 'OUT', self.root/'data'/'crawl'/'ctrip_ranked_candidates.json'), \
             patch.object(base, 'verify_one', side_effect=verify) as article, \
             patch.object(base, 'get', return_value=(200, '', b'<html/>')), redirect_stdout(StringIO()):
            ctrip.run(area='颐和园', max_pages=1)
        self.assertEqual(article.call_count, len(base.BEIJING_SEEDS))
        self.assertEqual({c.args[0]['url'] for c in article.call_args_list}, set(base.BEIJING_SEEDS))
        self.assertTrue((self.root/'data'/'crawl'/'ctrip_ranked_log.json').is_file())

    def test_ctrip_retry_refreshes_a_failed_cached_page(self):
        pages = self.root/'data/raw/pages'
        pages.mkdir(parents=True)
        saved = pages/'CTRIP_123.html'
        saved.write_bytes(b'<html>verification</html>')
        text = '我们从东宫门出发，先游览仁寿殿，然后沿长廊走到佛香阁。' * 6
        fixture = f'<html><meta charset="utf-8"><h1>我的颐和园游记</h1><div class="travel-content-wrapper"><p>{text}</p></div></html>'.encode()
        with patch.object(base, 'PAGES', pages), patch.object(base, 'get', return_value=(200, '', fixture)) as request:
            row = base.verify_one({'scenic_area':'颐和园', 'url':'https://you.ctrip.com/travels/beijing1/123.html'}, refresh=True)
        request.assert_called_once()
        self.assertTrue(row['accepted'], row)
        self.assertEqual(saved.read_bytes(), fixture)


if __name__ == '__main__':
    unittest.main()
