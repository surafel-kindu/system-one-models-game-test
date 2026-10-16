from html.parser import HTMLParser
from urllib.parse import urlsplit
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from app import create_app
from benchmarks import BenchmarkIndex
from submissions import SubmissionStore

def header(rid='test',game='dino'):
    return {'type':'run','run_id':rid,'game':game,'ts':123,'params':{'format':'average','games':2,'seed':42,'control':'assisted','versions':{game:'arcade-v2'}}}

def result(rid='test',player='greedy',score=10):
    return {'type':'result','run_id':rid,'game':'dino','player':player,'avg_score':score,'scores':[score,score],'games':2}

def suggestion(kind='model',name='Example'):
    return {'kind':kind,'name':name,'author':'Test Creator','source_url':'https://huggingface.co/example/model',
            'author_url':'https://github.com/example','description':'A local decision model for selecting from a stable set of game action candidates.',
            'instructions':'Install the published package, load the checkpoint, and map output probabilities to candidate IDs.',
            'license':'Apache-2.0','delivery_mode':'console' if kind=='game' else ''}

class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def write(self,name,records):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(json.dumps(r)+'\n' for r in records));return path
    def test_logs_exports_and_checkpoint_replacement_are_deduplicated(self):
        records=[header(),result()|{'type':'checkpoint'},result(),{'type':'status','run_id':'test','status':'complete','finished_at':124}]
        self.write('archive.jsonl',records)
        (self.root/'nested').mkdir()
        (self.root/'nested/export.json').write_text(json.dumps({'run_id':'test','records':records}))
        data=BenchmarkIndex(self.root).load()
        self.assertEqual(len(data['runs']),1)
        run=data['runs'][0]
        self.assertEqual(run['status'],'complete');self.assertEqual(len(run['results']),1)
        self.assertEqual(run['results'][0]['type'],'result');self.assertEqual(len(run['sources']),2)
    def test_repeated_chess_matches_survive_overlapping_exports(self):
        match={'type':'result','run_id':'chess','game':'chess','player':'a','vs':'b','result':'1-0','plies':20}
        records=[header('chess','chess'),match,match]
        self.write('one.jsonl',records)
        (self.root/'two.json').write_text(json.dumps({'records':records}))
        self.assertEqual(len(BenchmarkIndex(self.root).load()['runs'][0]['results']),2)
    def test_incomplete_trailing_write_does_not_hide_valid_results(self):
        path=self.write('partial.jsonl',[header(),result()])
        with path.open('a') as f:f.write('{"type":"status"')
        data=BenchmarkIndex(self.root).load()
        self.assertEqual(len(data['runs'][0]['results']),1);self.assertTrue(data['warnings'])
        self.assertEqual(data['runs'][0]['status'],'unfinished')
    def test_cache_observes_changed_and_new_files(self):
        path=self.write('one.jsonl',[header(),result()])
        index=BenchmarkIndex(self.root)
        self.assertEqual(index.load()['runs'][0]['results'][0]['avg_score'],10)
        self.write('one.jsonl',[header(),result(score=200)])
        self.assertEqual(index.load()['runs'][0]['results'][0]['avg_score'],200)
        self.write('two.jsonl',[header('new'),result('new')])
        self.assertEqual(len(index.load()['runs']),2)
    def test_legacy_and_unknown_metadata_remain_explicit(self):
        self.write('old.jsonl',[{'type':'run','run_id':'old','game':'2048','params':{},'ts':1}])
        run=BenchmarkIndex(self.root).load()['runs'][0]
        self.assertEqual(run['status'],'legacy');self.assertEqual(run['control'],'unspecified')
        self.assertTrue(run['legacy'])
        self.assertEqual(run['format'],'unspecified')
    def test_overall_coverage_keeps_planned_missing_games(self):
        rec=header()|{'params':{'format':'average','suites':['dino','flappy','chess']}}
        self.write('partial-suite.jsonl',[rec,result()])
        run=BenchmarkIndex(self.root).load()['runs'][0]
        self.assertEqual(run['games'],['dino'])
        self.assertEqual(run['expected_games'],['chess','dino','flappy'])
    def test_bad_json_nonfinite_values_and_external_symlinks_are_skipped(self):
        (self.root/'bad.json').write_text('{"records": [NaN]}')
        with tempfile.TemporaryDirectory() as external:
            secret=Path(external)/'outside.json';secret.write_text(json.dumps({'records':[header()]}))
            (self.root/'linked.json').symlink_to(secret)
            data=BenchmarkIndex(self.root).load()
        self.assertEqual(data['runs'],[]);self.assertTrue(data['warnings'])
    def test_import_tool_skips_unrelated_json_and_its_own_destination(self):
        self.write('source.jsonl',[header(),result()])
        (self.root/'unrelated.json').write_text('{"private_config":"not a benchmark"}')
        destination=self.root/'published'
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'tools/import_benchmarks.py'),str(self.root),'--destination',str(destination)]
        subprocess.run(command,check=True,capture_output=True)
        subprocess.run(command,check=True,capture_output=True)
        self.assertEqual([p.name for p in destination.rglob('*') if p.is_file()],['source.jsonl'])

class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'benchmarks').mkdir()
        records=[header(),result(),{'type':'status','run_id':'test','status':'complete','finished_at':124}]
        (self.root/'benchmarks/run.json').write_text(json.dumps({'records':records}))
        self.config={'TESTING':True,'DATA_DIR':str(self.root/'data'),'BENCHMARK_DIR':str(self.root/'benchmarks'),'SUBMISSIONS_PER_HOUR':3}
        self.app=create_app(self.config);self.client=self.app.test_client()
    def tearDown(self):
        self.temp.cleanup()
    def csrf(self):
        self.client.get('/submit')
        with self.client.session_transaction() as s:return s['csrf']
    def submit(self,payload,token=None,**headers):
        return self.client.post('/submit',json=payload,headers={'X-CSRF-Token':token or self.csrf(),**headers})
    def test_all_pages_assets_and_health_render(self):
        for path in ('/','/benchmarks','/project','/contribute','/submit','/submit?kind=game','/static/site.css','/static/benchmarks.js','/healthz'):
            with self.subTest(path=path):
                with self.client.get(path) as response:self.assertEqual(response.status_code,200)
    @staticmethod
    def page_head(response):
        class Head(HTMLParser):
            def __init__(self):
                super().__init__();self.meta={};self.links={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='meta':self.meta[attrs.get('property',attrs.get('name',''))]=attrs.get('content','')
                elif tag=='link':self.links[attrs.get('rel','')]=attrs.get('href','')
        head=Head();head.feed(response.get_data(as_text=True));return head
    def test_public_pages_have_distinct_server_rendered_share_cards(self):
        app=create_app(self.config|{'PUBLIC_URL':'https://arcade.afroawi.com'})
        client=app.test_client();titles=set();images=set()
        pages=[('/', '/'),('/benchmarks?game=dino&run=arbitrary','/benchmarks'),
               ('/project','/project'),('/contribute','/contribute'),
               ('/submit?kind=model','/submit'),('/submit?kind=game','/submit?kind=game')]
        for path,canonical in pages:
            with self.subTest(path=path):
                response=client.get(path,headers={'Host':'spoofed.example'})
                head=self.page_head(response);meta=head.meta
                self.assertEqual(response.status_code,200)
                self.assertEqual(head.links['canonical'],'https://arcade.afroawi.com'+canonical)
                self.assertEqual(meta['og:url'],head.links['canonical'])
                self.assertEqual(meta['og:type'],'website')
                self.assertEqual(meta['og:site_name'],'Model Arcade Lab')
                self.assertEqual(meta['twitter:card'],'summary_large_image')
                self.assertEqual(meta['twitter:image'],meta['og:image'])
                self.assertEqual(meta['description'],meta['og:description'])
                self.assertEqual(meta['twitter:description'],meta['description'])
                self.assertTrue(meta['og:image:alt']);self.assertTrue(meta['description'])
                self.assertEqual(meta['og:image:width'],'1200');self.assertEqual(meta['og:image:height'],'630')
                image=urlsplit(meta['og:image']);self.assertEqual(image.netloc,'arcade.afroawi.com')
                with client.get(image.path) as asset:
                    self.assertEqual(asset.status_code,200);self.assertEqual(asset.mimetype,'image/jpeg')
                    self.assertTrue(asset.data.startswith(b'\xff\xd8\xff'));self.assertLess(len(asset.data),500000)
                titles.add(meta['og:title']);images.add(meta['og:image'])
        self.assertEqual(len(titles),6);self.assertEqual(len(images),6)
    def test_share_metadata_follows_local_origin_without_public_url(self):
        app=create_app(self.config|{'PUBLIC_URL':''});client=app.test_client()
        head=self.page_head(client.get('/project',base_url='http://localhost:28482'))
        self.assertEqual(head.links['canonical'],'http://localhost:28482/project')
        self.assertTrue(head.meta['og:image'].startswith('http://localhost:28482/static/social/'))
    def test_receipts_and_missing_pages_are_not_indexed(self):
        head=self.page_head(self.client.get('/not-a-real-page'))
        self.assertEqual(head.meta['robots'],'noindex, nofollow');self.assertNotIn('canonical',head.links)
        payload=suggestion()|{'csrf':self.csrf()}
        receipt=self.client.post('/submit',data=payload)
        self.assertEqual(receipt.status_code,201)
        head=self.page_head(receipt)
        self.assertEqual(head.meta['robots'],'noindex, nofollow');self.assertNotIn('og:url',head.meta)
    def test_benchmark_filter_detail_download_and_not_found(self):
        self.assertEqual(len(self.client.get('/api/runs?game=dino&control=assisted').json['runs']),1)
        self.assertEqual(self.client.get('/api/runs?game=chess').json['runs'],[])
        self.assertEqual(self.client.get('/api/runs/test').json['results'][0]['player'],'greedy')
        download=self.client.get('/api/runs/test/download')
        self.assertIn('attachment;',download.headers['Content-Disposition'])
        self.assertEqual(self.client.get('/api/runs/missing').status_code,404)
        self.assertEqual(self.client.get('/data/submissions.sqlite3').status_code,404)
    def test_model_and_console_game_are_persisted_with_creator_metadata(self):
        first=self.submit(suggestion());second=self.submit(suggestion('game','New Game'))
        self.assertEqual(first.status_code,201);self.assertTrue(first.json['reference'].startswith('ARC-'))
        self.assertEqual(second.status_code,201);self.assertIn('/issues/new?',first.json['issue_url'])
        rows=self.app.extensions['submission_store'].all()
        self.assertEqual(len(rows),2)
        self.assertEqual({r['payload']['author'] for r in rows},{'Test Creator'})
        self.assertEqual(next(r for r in rows if r['kind']=='game')['payload']['delivery_mode'],'console')
        restarted=create_app(self.config)
        self.assertEqual(len(restarted.extensions['submission_store'].all()),2)
        self.assertEqual(self.app.secret_key,restarted.secret_key)
    def test_duplicate_is_idempotent_and_limit_is_persistent(self):
        token=self.csrf();payload=suggestion()
        first=self.submit(payload,token);again=self.submit(payload,token)
        self.assertEqual(again.status_code,200);self.assertEqual(first.json['reference'],again.json['reference'])
        for i in range(2):self.assertEqual(self.submit(suggestion(name='New '+str(i)),token).status_code,201)
        response=self.submit(suggestion(name='Over limit'),token)
        self.assertEqual(response.status_code,429);self.assertEqual(response.headers['Retry-After'],'3600')
    def test_csrf_and_foreign_origin_are_rejected(self):
        self.assertEqual(self.client.post('/submit',json=suggestion()).status_code,403)
        token=self.csrf()
        self.assertEqual(self.submit(suggestion(),token,Origin='https://foreign.example').status_code,403)
        self.assertEqual(self.submit(suggestion(),'非ASCII').status_code,403)
        self.assertEqual(self.submit(suggestion(),token,Origin='https://[').status_code,403)
    def test_invalid_urls_fields_honeypot_and_oversize_are_rejected(self):
        token=self.csrf()
        for change in ({'source_url':'javascript:alert(1)'},{'source_url':'https://user:password@example.com'},{'author':''},{'description':'too short'},{'kind':'other'},{'company':'spam'}):
            response=self.submit(suggestion()|change,token)
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.submit(suggestion()|{'instructions':'X'*30000},token).status_code,413)
        self.assertEqual(len(self.app.extensions['submission_store'].all()),0)
    def test_native_form_fallback_and_review_status(self):
        token=self.csrf();response=self.client.post('/submit',data=suggestion()|{'csrf':token})
        self.assertEqual(response.status_code,201);self.assertIn(b'SUGGESTION RECEIVED',response.data)
        store=self.app.extensions['submission_store'];reference=store.all()[0]['id']
        self.assertTrue(store.update(reference,'in-review','Checking the source'))
        self.assertEqual(store.all('in-review')[0]['note'],'Checking the source')
    def test_long_unicode_suggestion_has_a_usable_issue_link(self):
        payload=suggestion()|{'description':'🧩'*1000,'instructions':'Detailed integration notes. '*200}
        response=self.submit(payload)
        self.assertEqual(response.status_code,201)
        self.assertLess(len(response.json['issue_url']),7500)
        self.assertEqual(self.app.extensions['submission_store'].all()[0]['payload']['instructions'],payload['instructions'].strip())
    def test_headers_and_private_queue(self):
        response=self.client.get('/submit')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(self.client.get('/api/submissions').status_code,404)
    def test_friendly_player_names_and_public_url_origin(self):
        (self.root/'benchmarks/friendly.json').write_text(json.dumps({'records':[header('friendly'),result('friendly',player='jev')]}))
        data=self.client.get('/api/runs?q=Jev-BERTa').json
        self.assertEqual(len(data['runs']),1)
        self.assertEqual(data['runs'][0]['players'],['jev'])
        app=create_app(self.config|{'PUBLIC_URL':'https://arcade.example.com'})
        client=app.test_client();client.get('/submit')
        with client.session_transaction() as s:token=s['csrf']
        self.assertEqual(client.post('/submit',json=suggestion(),headers={'X-CSRF-Token':token,'Origin':'https://arcade.example.com'}).status_code,201)
    def test_shared_database_enforces_limit_across_workers(self):
        stores=[SubmissionStore(self.root/'shared') for _ in range(6)]
        def send(i):return stores[i].save(suggestion(name='Concurrent '+str(i)),'127.0.0.1',2)[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            accepted=list(pool.map(send,range(6)))
        self.assertEqual(sum(ref is not None for ref in accepted),2)
        self.assertEqual(len(stores[0].all()),2)

if __name__=='__main__':
    unittest.main()
