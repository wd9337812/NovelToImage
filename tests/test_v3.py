import base64
import copy
from datetime import date
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/zhihu-comic-cpa/scripts"
sys.path.insert(0, str(SCRIPTS))
import comic
from comic_v3.core import ProductionError, fingerprint, write_json, validate_plan, migrate_legacy
from comic_v3.provider import validate_profile, ImageProvider
from comic_v3.scheduler import Scheduler, retry_after, CachedSubmission
from comic_v3.render import Letterer
from comic_v3.pipeline import Production, export


def profile(mode="sync", cap=1, gap=0, rpm=None):
    value = {"version": 1, "provider": "test", "model": "test-image", "base_url": "https://images.example/v1",
            "api_key_env": "TEST_IMAGE_KEY", "quota_pool": "test-project", "resolution": "1K",
            "protocol": {"mode": mode, "dialect": "agnes", "task_id_path": "id", "poll_url_path": "polling_url",
                         "poll_hosts": ["images.example"]},
            "capabilities": {"ratios": ["3:4", "4:3", "3:2", "2:3", "21:9"], "references": True},
            "limits": {"max_inflight": cap, "start_interval_seconds": gap, "requests_per_minute": rpm,
                       "images_per_day": None, "poll_interval_seconds": 0},
            "cost": {"status": "free_confirmed"}, "max_retries": 1,
            "research": {"checked_on": "2020-01-01", "recheck_after": "2099-01-01",
                         "decision": "Synthetic test fixture, never a real provider quota.",
                         "sources": [{"url": "https://images.example/docs", "supports": "synthetic test"}]}}
    value["research"]["applies_to"] = {k:value[k] for k in ("provider","model","base_url","resolution","quota_pool")}
    return value


def plan():
    return {"version": 3, "keyword": "雨夜来信", "mode": "style_pilot",
            "style": {"id": "test", "prompt": "original comic"},
            "characters": [{"id": "hero", "name": "小雨", "appearance": "short black hair", "versions": {"base": "blue coat"}, "reference_assets": {"base": ["hero-sheet"]}}],
            "assets": [{"id": "hero-sheet", "prompt": "Hero identity sheet, short black hair and blue coat"}], "pages": [{"id": "page-open", "route": "panels", "purpose": "发现信件",
                "layout": {"rationale": "发现信件的一个瞬间，使用单幅建立环境。", "reading_order": ["panel-letter"]},
                "reader": {"known": "雨夜", "new": "信出现", "open": "谁写的"},
                "panels": [{"id": "panel-letter", "box": [0,0,1,1], "scene": "rainy room", "action": "opens letter", "emotion": "surprised",
                    "source_quote": "雨停了", "actors": [{"character": "hero", "version": "base", "protect": [.3,.32,.4,.5]}],
                    "texts": [{"type": "dialogue", "speaker": "hero", "text": "谁的信？", "box": [.03,.03,.6,.2], "tail": [.5,.35]}]}]}]}


def image_response():
    output = io.BytesIO(); Image.new("RGB", (864,1152), "#e8edf1").save(output, format="PNG")
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"data": [{"b64_json": base64.b64encode(output.getvalue()).decode()}]}
    return response


class V3Tests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT/"runs"/"test-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def scheduler(self, p=None, run="test", budget=10, clock=None):
        kwargs = {} if clock is None else {"clock": clock.now, "sleep": clock.sleep}
        return Scheduler(self.root/"state.sqlite3", p or profile(), run, budget, **kwargs)

    def test_profile_requires_current_research_and_separate_rate_and_concurrency(self):
        validate_profile(profile(), date(2026,10,20))
        for update in ({"sources": []}, {"recheck_after": "2021-01-01"}, {"decision": ""}):
            p = profile(); p["research"].update(update)
            with self.assertRaises(ProductionError): validate_profile(p, date(2026,10,20))
        p = profile(); p["limits"]["start_interval_seconds"] = None
        with self.assertRaises(ProductionError): validate_profile(p)
        p=profile();p["model"]="another-model"
        with self.assertRaisesRegex(ProductionError,"重新查资料"):validate_profile(p)
        p=profile(cap=2);p["research"]["user_constraints"]={"request_mode":"serial"}
        with self.assertRaisesRegex(ProductionError,"串行"):validate_profile(p)

    def test_source_speaker_outfit_and_protected_area_are_real_constraints(self):
        validate_plan(plan(), "雨停了", "雨夜来信")
        for mutation in ("source", "speaker", "outfit", "bubble", "keyword"):
            p = plan(); panel=p["pages"][0]["panels"][0]
            if mutation == "source": panel["source_quote"] = "不存在"
            if mutation == "speaker": panel["texts"][0]["speaker"] = "other"
            if mutation == "outfit": panel["actors"][0]["version"] = "unplanned"
            if mutation == "bubble": panel["texts"][0]["box"] = [.3,.35,.4,.4]
            if mutation == "keyword": p["keyword"] = "错误词"
            with self.assertRaises(ProductionError): validate_plan(p, "雨停了", "雨夜来信")

    def test_character_versions_require_bound_identity_assets(self):
        for change in ('missing', 'unknown', 'wrong-version'):
            p=plan()
            if change=='missing': p['characters'][0].pop('reference_assets')
            if change=='unknown': p['characters'][0]['reference_assets']['base']=['unknown-sheet']
            if change=='wrong-version': p['characters'][0]['reference_assets']={'other':['hero-sheet']}
            with self.assertRaisesRegex(ProductionError,'人物参考图'):
                validate_plan(p,'雨停了')

    def test_layout_requires_reason_reading_order_and_nonoverlap(self):
        for change in ('reason','order','overlap'):
            p=plan(); page=p['pages'][0]
            if change=='reason': page['layout'].pop('rationale')
            elif change=='order': page['layout']['reading_order']=[]
            else:
                frame=copy.deepcopy(page['panels'][0]);frame['id']='overlap-frame'
                page['panels'].append(frame);page['layout']['reading_order'].append(frame['id'])
            with self.assertRaises(ProductionError): validate_plan(p,'雨停了')
        p=plan()
        for n in range(2):
            page=copy.deepcopy(p['pages'][0]);page['id']=f'page-copy-{n}'
            page['panels'][0]['id']=f'panel-copy-{n}'
            page['layout']['reading_order']=[f'panel-copy-{n}'];p['pages'].append(page)
        with self.assertRaisesRegex(ProductionError,'重复同一布局'): validate_plan(p,'雨停了')
        p['layout_repetition_reason']='用户指定相同布局以对照连续三个同机位反应。'
        validate_plan(p,'雨停了')

    def imported_case(self):
        p=plan(); image=self.root/'identity.png'
        image.write_bytes(base64.b64decode(image_response().json()['data'][0]['b64_json']))
        p['assets'][0]['local_path']='identity.png'
        root=self.root/'production'; cfg=profile();cfg['runtime']={'state_file':str(self.root/'import-state.sqlite3')}
        cfg['max_retries']=0
        transport=Mock(return_value=image_response())
        job=Production(p,cfg,'雨停了',root,comic,transport=transport,asset_base=self.root)
        job.run(stage='assets'); transport.assert_not_called()
        asset=root/'assets/hero-sheet.png'
        write_json(root/'asset-review.json',{'hero-sheet':{'accepted':True,'sha256':fingerprint(asset.read_bytes()),'reviewer':'synthetic fixture'}})
        return p,cfg,root,transport

    def test_imported_identity_is_actually_sent_and_packaged_without_local_path(self):
        p,cfg,root,transport=self.imported_case()
        with patch.dict(os.environ,TEST_IMAGE_KEY='fake-test'):
            Production(p,cfg,'雨停了',root,comic,transport=transport,asset_base=self.root).run()
        body=transport.call_args.args[2]
        submitted=body['extra_body']['image'];self.assertEqual(len(submitted),1)
        asset=(root/'assets/hero-sheet.png').read_bytes()
        self.assertEqual(base64.b64decode(submitted[0].split(',',1)[1]),asset)
        manifest=json.loads((root/'production.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['jobs']['panel-letter']['actual_reference_count'],1)
        with self.assertRaises(ProductionError):export(root)
        _,trace=export(root,allow_unreviewed=True)
        with zipfile.ZipFile(trace) as z:
            self.assertEqual(z.read('references/hero-sheet.png'),asset)
            portable=json.loads(z.read('storyboard.json'))
            self.assertEqual(portable['assets'][0]['local_path'],'references/hero-sheet.png')
            self.assertNotIn(str(self.root),z.read('storyboard.json').decode())
        manifest['jobs']['panel-letter']['actual_reference_count']=0
        write_json(root/'production.json',manifest)
        with self.assertRaisesRegex(ProductionError,'实际参考图'):export(root,allow_unreviewed=True)
        manifest['jobs']['panel-letter']['actual_reference_count']=1
        write_json(root/'production.json',manifest)
        for archive in root.glob('*.zip'):archive.unlink()
        (root/'assets/hero-sheet.png').unlink()
        with self.assertRaisesRegex(ProductionError,'缺少匹配'):export(root,allow_unreviewed=True)
        self.assertFalse(list(root.glob('*.zip')))

    def test_unreviewed_identity_and_unsupported_model_stop_before_page_calls(self):
        p,cfg,root,transport=self.imported_case()
        (root/'asset-review.json').unlink()
        with self.assertRaisesRegex(ProductionError,'不需要用户确认'):
            Production(p,cfg,'雨停了',root,comic,transport=transport,asset_base=self.root).run()
        transport.assert_not_called()
        cfg['capabilities']['references']=False
        with self.assertRaisesRegex(ProductionError,'禁止无参考降级'):
            Production(p,cfg,'雨停了',root,comic,transport=transport,asset_base=self.root).run()
        transport.assert_not_called()

    def test_reference_failure_stops_before_next_serial_page(self):
        p,cfg,root,transport=self.imported_case()
        page=copy.deepcopy(p['pages'][0]);page['id']='another-page'
        page['panels'][0]['id']='another-panel';page['layout']['reading_order']=['another-panel']
        p['pages'].append(page)
        transport.return_value=Mock(status_code=503,headers={})
        with patch.dict(os.environ,TEST_IMAGE_KEY='fake-test'):
            with self.assertRaisesRegex(ProductionError,'HTTP503'):
                Production(p,cfg,'雨停了',root,comic,transport=transport,asset_base=self.root).run()
        self.assertEqual(transport.call_count,1)

    def test_one_three_four_panel_storyboards_and_all_routes_keep_identity_proof(self):
        p=json.loads((ROOT/'skills/zhihu-comic-cpa/references/plan-v3.example.json').read_text(encoding='utf-8'))
        story=(ROOT/'examples/story.txt').read_text(encoding='utf-8')
        self.assertEqual([len(x['panels']) for x in p['pages']],[1,3,4])
        root=self.root/'layouts'
        Production(p,profile(),story,root,comic,mock=True).run()
        m=json.loads((root/'production.json').read_text(encoding='utf-8'))
        self.assertEqual(len(m['pages']),3)
        for page in m['pages'].values():
            for jid in page['job_ids']:
                bindings=m['jobs'][jid]['identity_bindings']
                if bindings:self.assertGreater(m['jobs'][jid]['actual_reference_count'],0)
        album,_=export(root)
        with zipfile.ZipFile(album) as z:self.assertEqual(len(z.namelist()),3)

    def test_persistent_gap_and_rolling_rpm_apply_even_with_parallel_capacity(self):
        class Clock:
            def __init__(self): self.value=1000
            def now(self): return self.value
            def sleep(self, seconds): self.value+=seconds
        clock=Clock(); p=profile(cap=3, gap=2, rpm=2)
        a=self.scheduler(p,clock=clock).acquire("first")
        self.scheduler(p,clock=clock).finish(a,"done")
        b=self.scheduler(p,clock=clock).acquire("second")
        self.assertEqual(clock.value,1002)
        self.scheduler(p,clock=clock).finish(b,"done")
        self.scheduler(p,clock=clock).acquire("third")
        self.assertGreaterEqual(clock.value,1060)

    def test_multiple_instances_share_inflight_cap_and_unknown_blocks_pool(self):
        scheduler=self.scheduler(); ticket=scheduler.acquire("one")
        scheduler.finish(ticket,"unknown")
        with self.assertRaisesRegex(ProductionError,"未知"):
            self.scheduler(run="another").acquire("two")

    def test_two_workers_cannot_overrun_shared_capacity(self):
        p=profile(cap=1);p["max_queue_wait_seconds"]=30
        first=self.scheduler(p).acquire("one")
        acquired=threading.Event(); errors=[]
        def worker():
            try:
                self.scheduler(p,run="other").acquire("two")
                acquired.set()
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=worker);thread.start()
        self.assertFalse(acquired.wait(.1))
        self.scheduler(p).finish(first,"done")
        thread.join(3)
        self.assertTrue(acquired.is_set());self.assertFalse(errors)

    def test_async_poll_never_sends_auth_to_an_unverified_host(self):
        p=profile("async");scheduler=self.scheduler(p);ticket=scheduler.acquire("foreign")
        scheduler.finish(ticket,"submitted",{"id":"task-1","url":"https://untrusted.example/result"})
        transport=Mock();provider=ImageProvider(p,scheduler,comic,transport=transport)
        with self.assertRaisesRegex(ProductionError,"域名未核验"):
            provider.generate("foreign","p","3:4",[])
        transport.assert_not_called()

    def test_budget_counts_failed_attempts_and_daily_pool_is_shared(self):
        scheduler=self.scheduler(budget=1); t=scheduler.acquire("bad"); scheduler.finish(t,"failed")
        with self.assertRaisesRegex(ProductionError,"预算"): scheduler.acquire("retry")
        p=profile(); p["limits"]["images_per_day"]=1
        with self.assertRaisesRegex(ProductionError,"每日"):
            self.scheduler(p,run="another").acquire("new-run")

    def test_timeout_marks_unknown_instead_of_automatic_duplicate(self):
        import requests
        scheduler=self.scheduler()
        provider=ImageProvider(profile(),scheduler,comic,transport=Mock(side_effect=requests.ReadTimeout()))
        with patch.dict(os.environ,TEST_IMAGE_KEY="fake-test"):
            with self.assertRaisesRegex(ProductionError,"可能仍在生成"): provider.generate("j","prompt","3:4",[])
            with self.assertRaises(ProductionError): provider.generate("j","prompt","3:4",[])
        self.assertEqual(provider.transport.call_count,1)
        self.assertEqual(scheduler.report()["image_attempts"],1)

    def test_missing_key_does_not_leave_a_phantom_inflight_task(self):
        scheduler=self.scheduler();provider=ImageProvider(profile(),scheduler,comic,transport=Mock())
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ProductionError):provider.generate("no-key","p","3:4",[])
        self.assertEqual(scheduler.report()["image_attempts"],0)

    def test_async_resume_queries_existing_task_and_never_submits_twice(self):
        p=profile("async"); scheduler=self.scheduler(p)
        ticket=scheduler.acquire("async-job")
        scheduler.finish(ticket,"submitted",{"id":"task-1","url":"https://images.example/result/1"})
        response=image_response(); payload=response.json(); payload["status"]="Ready"; response.json.return_value=payload
        transport=Mock(return_value=response); provider=ImageProvider(p,scheduler,comic,transport=transport)
        with patch.dict(os.environ,TEST_IMAGE_KEY="fake-test"):
            self.assertTrue(provider.generate("async-job","prompt","3:4",[]).startswith(b"\x89PNG"))
        self.assertEqual(transport.call_args.args[0],"GET")
        self.assertEqual(scheduler.report()["image_attempts"],1)

    def test_completed_response_survives_download_failure_without_resubmission(self):
        scheduler=self.scheduler(); provider=ImageProvider(profile(),scheduler,comic,transport=Mock(return_value=image_response()))
        with patch.dict(os.environ,TEST_IMAGE_KEY="fake-test"):
            with patch.object(provider,"decode",side_effect=ProductionError("download failed")):
                with self.assertRaises(ProductionError): provider.generate("cached-response","prompt","3:4",[])
            self.assertTrue(provider.generate("cached-response","prompt","3:4",[]))
        self.assertEqual(provider.transport.call_count,1)

    def test_same_job_waits_for_cached_response_even_with_parallel_capacity(self):
        p=profile(cap=2)
        first=self.scheduler(p)
        ticket=first.acquire('same-job')
        waiting=self.scheduler(p,run='other-run')
        waiting.sleep=lambda seconds: first.finish(ticket,'done',{'data':[]})
        with self.assertRaises(CachedSubmission) as result:
            waiting.acquire('same-job')
        self.assertEqual(result.exception.data,{'data':[]})
        self.assertEqual(waiting.report()['image_attempts'],0)
        self.assertEqual(first.report()['image_attempts'],1)

    def test_retry_after_dates_and_quota_rejection_do_not_loop(self):
        self.assertEqual(retry_after("Thu, 01 Jan 1970 00:01:40 GMT",90,5),10)
        provider=ImageProvider(profile(),self.scheduler(),comic,transport=Mock(return_value=Mock(status_code=429,text="daily quota exceeded",headers={})))
        with patch.dict(os.environ,TEST_IMAGE_KEY="fake-test"):
            with self.assertRaises(ProductionError): provider.generate("quota","p","3:4",[])
        self.assertEqual(provider.transport.call_count,1)

    def test_readable_font_failure_stops_instead_of_shrinking(self):
        renderer=Letterer(comic.font_path(comic.load_config()))
        with self.assertRaises(ProductionError):
            renderer.label(Image.new("RGB",(1080,1440)),{"type":"narration","text":"很长的文本"*80},[10,10,180,100])

    def test_observed_face_region_relettering_does_not_regenerate_art(self):
        p=plan();root=self.root/'observed-regions'
        Production(p,profile(),'雨停了',root,comic,mock=True).run()
        old=json.loads((root/'production.json').read_text(encoding='utf-8'))
        changed=copy.deepcopy(p);panel=changed['pages'][0]['panels'][0]
        actor=panel['actors'][0];actor['art_protect']=actor['protect'];actor['protect']=[.3,.25,.4,.4]
        text=panel['texts'][0];text['art_box']=text['box'];text['box']=[.03,.72,.6,.2]
        Production(changed,profile(),'雨停了',root,comic,mock=True).run()
        new=json.loads((root/'production.json').read_text(encoding='utf-8'))
        self.assertEqual(old['jobs']['panel-letter']['cache_key'],new['jobs']['panel-letter']['cache_key'])
        self.assertTrue(new['jobs']['panel-letter']['reused'])

    def test_partial_render_keeps_raw_cache_and_export_rejects_stale_review(self):
        p=plan(); root=self.root/"runs"/"case"
        production=Production(p,profile(),"雨停了",root,comic,mock=True)
        production.run(); first=json.loads((root/"production.json").read_text(encoding="utf-8"))
        cache=first["jobs"]["panel-letter"]["cache_key"]
        changed=copy.deepcopy(p);changed["pages"][0]["font_size"]=43
        Production(changed,profile(),"雨停了",root,comic,mock=True).run()
        second=json.loads((root/"production.json").read_text(encoding="utf-8"))
        self.assertEqual(cache,second["jobs"]["panel-letter"]["cache_key"])
        self.assertTrue(second["jobs"]["panel-letter"]["reused"])
        # Treat it as an actual image set to exercise the required visual-review gate.
        second["mock"]=False;write_json(root/"production.json",second)
        with self.assertRaises(ProductionError):export(root)
        page=second["pages"]["page-open"]
        checks={k:True for k in ("source_fidelity","character_continuity","acting_composition","exact_text","reading_order","mobile_readability")}
        write_json(root/"visual-review.json",{"page-open":{"sha256":page["sha256"],"verdict":"accepted","blocking_issues":[],"checks":checks}})
        album,trace=export(root)
        with zipfile.ZipFile(album) as z:
            self.assertEqual(z.namelist(),["01-page-open.png"])
        with zipfile.ZipFile(trace) as z:
            self.assertFalse(any(x in z.namelist() for x in ["provider-profile.json","state.sqlite3","story.txt"]))

    def test_legacy_import_preserves_original_text_and_source(self):
        old=json.loads((ROOT/"examples/plan.json").read_text(encoding="utf-8"))
        story=(ROOT/"examples/story.txt").read_text(encoding="utf-8").strip()
        migrated=migrate_legacy(old,story)
        self.assertEqual(len(migrated["pages"]),len(old["pages"]))
        self.assertEqual(migrated["legacy_metadata"]["hook"],old["hook"])


if __name__ == "__main__": unittest.main()
