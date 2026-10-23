import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/zhihu-comic-cpa/scripts'))
import comic
from comic_v3.authoring import compile_beats
from comic_v3.core import ProductionError, fingerprint, read_json, write_json, validate_plan
from comic_v3.opening import OPENING_CHECKS, opening_binding, opening_report, opening_review_issues
from comic_v3.pipeline import Production, export
from comic_v3.__main__ import main
from test_v3 import profile


class OpeningTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'runs/test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.tmp.name)
        refs = ROOT/'skills/zhihu-comic-cpa/references'
        self.brief = read_json(refs/'opening-brief.example.json')
        self.beats = read_json(refs/'opening-beats.example.json')['pages']
        self.story = (ROOT/'examples/story.txt').read_text(encoding='utf-8').strip()
        self.plan = compile_beats(self.brief, self.beats, self.story)

    def tearDown(self):
        self.tmp.cleanup()

    def synthetic_review(self, plan, manifest):
        # Unit-test fixture only: never used to mark actual story art as inspected.
        return {'plan_hash': opening_binding(plan), 'verdict': 'accepted',
                'reviewer': 'synthetic fixture', 'blocking_issues': [],
                'page_hashes': {p['id']: manifest['pages'][p['id']]['sha256'] for p in plan['pages'][:3]},
                'checks': {key: True for key in OPENING_CHECKS},
                'observations': {key: 'Synthetic fixture tests binding, not image quality.' for key in OPENING_CHECKS}}

    def test_new_promotion_needs_strategy_but_legacy_is_only_diagnosed(self):
        brief = copy.deepcopy(self.brief)
        brief['mode'] = 'promotion_excerpt'
        brief.pop('opening')
        with self.assertRaisesRegex(ProductionError, '开场策略'):
            compile_beats(brief, self.beats, self.story)
        legacy = copy.deepcopy(self.plan)
        legacy.pop('opening'); legacy.pop('authoring_version')
        legacy['mode'] = 'promotion_excerpt'
        legacy['pages'][0] = compile_beats(read_json(ROOT/'skills/zhihu-comic-cpa/references/authoring-brief.example.json'),
                                         read_json(ROOT/'skills/zhihu-comic-cpa/references/authoring-beats.example.json')['pages'],
                                         self.story)['pages'][0]
        before = fingerprint(legacy)
        report = opening_report(validate_plan(legacy, self.story))
        self.assertEqual(report['status'], 'legacy_not_assessed')
        self.assertEqual(report['pages'][0]['panels'], 1)
        self.assertLess(report['pages'][0]['characters'], 45)
        self.assertEqual(before, fingerprint(legacy))

    def test_multiframe_source_backed_opening_and_tampered_source(self):
        report = opening_report(self.plan)
        self.assertEqual([p['panels'] for p in report['pages']], [3, 3, 2])
        self.assertTrue(report['required_review'])
        self.assertGreaterEqual(report['pages'][0]['characters'], 45)
        for location in ('candidate', 'page'):
            changed = copy.deepcopy(self.brief)
            target = changed['opening']['candidates'][0] if location == 'candidate' else changed['opening']['pages'][0]
            target['source_quote'] = '原文没有出现的阴谋'
            with self.assertRaisesRegex(ProductionError, '锚点不存在'):
                compile_beats(changed, self.beats, self.story)

    def test_setup_only_blocked_and_single_frame_needs_reason_not_word_padding(self):
        brief = copy.deepcopy(self.brief)
        brief['opening']['pages'][0]['beat'] = 'setup_only'
        with self.assertRaisesRegex(ProductionError, '仅介绍背景'):
            compile_beats(brief, self.beats, self.story)
        beats = copy.deepcopy(self.beats)
        beats[0]['layout'] = 'hero'; beats[0]['panels'] = beats[0]['panels'][1:2]
        with self.assertRaisesRegex(ProductionError, '单格首张'):
            compile_beats(self.brief, beats, self.story)
        brief = copy.deepcopy(self.brief)
        brief['opening']['single_panel_reason'] = '同一近景展示未拆红绳的锁和刚滑出的信；由反常证据而非站姿承担叙事，仍待实际审图。'
        p = compile_beats(brief, beats, self.story)
        self.assertEqual(len(p['pages'][0]['panels']), 1)
        self.assertLess(opening_report(p)['pages'][0]['characters'], 45)

    def test_premature_cta_and_broken_page_mapping_cannot_pass(self):
        beats = copy.deepcopy(self.beats); beats[1]['strong_cta'] = True
        with self.assertRaisesRegex(ProductionError, '强CTA'):
            compile_beats(self.brief, beats, self.story)
        brief = copy.deepcopy(self.brief)
        brief['opening']['pages'][1]['page_id'] = 'wrong-id'
        with self.assertRaisesRegex(ProductionError, '实际ID'):
            compile_beats(brief, self.beats, self.story)

    def test_explicit_non_social_scope_requires_documented_user_request(self):
        brief = copy.deepcopy(self.brief); brief['mode'] = 'promotion_excerpt'
        brief['opening'] = {'version': 1, 'scope': 'user_requested_cover', 'reason': '用户要求独立封面'}
        with self.assertRaisesRegex(ProductionError, '用户要求'):
            compile_beats(brief, self.beats, self.story)
        brief['opening']['user_instruction'] = '测试用的用户指令：单独制作一张封面。'
        report = opening_report(compile_beats(brief, self.beats, self.story))
        self.assertEqual(report['status'], 'scope_exempt')

    def test_batch_generation_stops_before_any_live_request_without_opening_review(self):
        p = copy.deepcopy(self.plan)
        later = copy.deepcopy(p['pages'][-1]); later['id'] = 'page-004'
        for index, panel in enumerate(later['panels']): panel['id'] = 'page-004-p'+str(index+1)
        later['layout']['reading_order'] = [s['id'] for s in later['panels']]
        p['pages'].append(later); p['pacing'] = {}
        cfg = profile(); cfg['runtime'] = {'state_file': str(self.root/'state.sqlite3')}
        production = Production(p, cfg, self.story, self.root/'album', comic)
        with patch('comic_v3.provider.ImageProvider.generate', side_effect=AssertionError('No live API allowed')) as generate:
            with self.assertRaisesRegex(ProductionError, '前三张内部试制'):
                production.run()
            generate.assert_not_called()
        self.assertEqual(production.manifest['status'], 'awaiting_opening_review')

    def test_strict_export_needs_opening_review_and_rejects_stale_image_or_strategy(self):
        cfg = profile(); cfg['runtime'] = {'state_file': str(self.root/'state.sqlite3')}
        root = self.root/'album'
        with patch('comic_v3.provider.ImageProvider.generate', side_effect=AssertionError('No live API allowed')):
            Production(self.plan, cfg, self.story, root, comic, mock=True).run()
        manifest = read_json(root/'production.json')
        manifest['mock'] = False  # Exercise strict gates with synthetic images only.
        write_json(root/'production.json', manifest)
        checks = ('source_fidelity', 'character_continuity', 'acting_composition', 'exact_text', 'reading_order', 'mobile_readability')
        write_json(root/'visual-review.json', {pid: {'sha256': page['sha256'], 'verdict': 'accepted',
                   'blocking_issues': [], 'checks': {**{k: True for k in checks}, 'cta_choice': True},
                   'cta_enabled': False, 'cta_notes': 'Synthetic no-CTA fixture, not actual visual approval.'}
                   for pid, page in manifest['pages'].items()})
        plan = read_json(root/'storyboard.json')
        with self.assertRaisesRegex(ProductionError, '开场专项验收'):
            export(root)
        review_zip, _ = export(root, allow_unreviewed=True)
        self.assertTrue(review_zip.name.startswith('REVIEW-'))
        review = self.synthetic_review(plan, manifest)
        write_json(root/'opening-review.json', review)
        self.assertEqual(opening_review_issues(plan, manifest, root), [])
        album, trace = export(root)
        self.assertFalse(album.name.startswith('REVIEW-'))
        with zipfile.ZipFile(trace) as z:
            self.assertIn('opening-review.json', z.namelist())
            self.assertIn('opening-report.json', z.namelist())
        changed = copy.deepcopy(plan); changed['opening']['selection_reason'] += '修改'
        self.assertTrue(opening_review_issues(changed, manifest, root))
        changed = copy.deepcopy(plan); changed['characters'][0]['appearance'] += ' changed hair'
        self.assertTrue(opening_review_issues(changed, manifest, root))
        changed = copy.deepcopy(plan); changed['pages'].append(copy.deepcopy(plan['pages'][-1]))
        self.assertEqual(opening_binding(changed), opening_binding(plan))
        review['observations']['conflict_visible'] = ''
        write_json(root/'opening-review.json', review)
        self.assertTrue(opening_review_issues(plan, manifest, root))
        write_json(root/'opening-review.json', self.synthetic_review(plan, manifest))
        image = root/manifest['pages'][plan['pages'][0]['id']]['file']
        image.write_bytes(image.read_bytes()+b'changed')
        self.assertTrue(opening_review_issues(plan, manifest, root))

    def test_completed_opening_allows_next_page_to_reach_production(self):
        p = copy.deepcopy(self.plan)
        later = copy.deepcopy(p['pages'][-1]); later['id'] = 'page-004'
        for index, panel in enumerate(later['panels']): panel['id'] = 'page-004-p'+str(index+1)
        later['layout']['reading_order'] = [s['id'] for s in later['panels']]
        p['pages'].append(later); p['pacing'] = {}
        cfg = profile(); cfg['runtime'] = {'state_file': str(self.root/'state.sqlite3')}
        root = self.root/'resume'
        with patch('comic_v3.provider.ImageProvider.generate', side_effect=AssertionError('No live API allowed')):
            Production(p, cfg, self.story, root, comic, mock=True).run([s['id'] for s in p['pages'][:3]])
        actual_plan = read_json(root/'storyboard.json')
        write_json(root/'opening-review.json', self.synthetic_review(actual_plan, read_json(root/'production.json')))
        production = Production(p, cfg, self.story, root, comic)
        with patch('comic_v3.pipeline.layout_preview', side_effect=RuntimeError('Reached production after review gate')):
            with self.assertRaisesRegex(RuntimeError, 'Reached production'):
                production.run(['page-004'])

    def test_opening_diagnostic_is_offline_and_never_loads_credentials(self):
        plan = self.root/'plan.json'; out = self.root/'report.json'
        write_json(plan, self.plan)
        with patch.object(comic, 'load_env', side_effect=AssertionError('Must not read credentials')):
            with patch('sys.stdout', new=io.StringIO()):
                result = main(['opening-check', '--plan', str(plan), '--out', str(out)], legacy=comic)
        self.assertEqual(result, 0)
        self.assertEqual(read_json(out)['plan_hash'], opening_binding(self.plan))

    def test_default_schema_shows_new_opening_and_keeps_technical_example_explicit(self):
        with patch.object(comic, 'load_env', side_effect=AssertionError('Must not read credentials')):
            for flags, expected in (([], 3), (['--technical-example'], 1)):
                output = io.StringIO()
                with patch('sys.stdout', new=output):
                    result = main(['schema', *flags], legacy=comic)
                self.assertEqual(result, 0)
                p = validate_plan(json.loads(output.getvalue()), self.story)
                self.assertEqual(len(p['pages'][0]['panels']), expected)


if __name__ == '__main__':
    unittest.main()
