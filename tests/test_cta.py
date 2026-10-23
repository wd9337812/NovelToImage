import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/zhihu-comic-cpa/scripts'))
import comic
from comic_v3.authoring import compile_beats, initialize
from comic_v3.core import ProductionError, read_json, validate_plan, write_json
from comic_v3.cta import cta_enabled
from comic_v3.pacing import pacing_report
from comic_v3.pipeline import Production, page_prompt, export
from comic_v3.__main__ import main
from test_v3 import profile


class CtaTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'runs/test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.tmp.name)
        refs = ROOT/'skills/zhihu-comic-cpa/references'
        self.brief = read_json(refs/'authoring-brief.example.json')
        self.beats = read_json(refs/'authoring-beats.example.json')['pages']
        self.story = (ROOT/'examples/story.txt').read_text(encoding='utf-8').strip()

    def tearDown(self):
        self.tmp.cleanup()

    def without_cta(self):
        brief = copy.deepcopy(self.brief); brief['cta'] = {'enabled': False}
        beats = copy.deepcopy(self.beats)
        beats[-1].pop('strong_cta')
        beats[-1]['panels'][-1]['texts'] = [{'type': 'narration', 'text': '父亲明明还在外地……\n门里到底是谁？'}]
        return brief, beats

    def test_init_preserves_pending_yes_and_no_without_defaulting(self):
        for index, choice in enumerate((None, True, False)):
            target = self.root/str(index)
            initialize('测试', 'standard', 'https://images.example/v1', 'example-model', target, final_cta=choice)
            brief = read_json(target/'brief.local.json')
            self.assertIs(brief['cta']['enabled'], choice)
            self.assertEqual(brief['authoring_version'], '3.5')
        brief = copy.deepcopy(self.brief)
        for value in (None, 'false', 0):
            brief['cta'] = {'enabled': value}
            with self.assertRaisesRegex(ProductionError, '尚未选择'):
                compile_beats(brief, self.beats, self.story)
        brief.pop('cta')
        with self.assertRaisesRegex(ProductionError, '先询问'):
            compile_beats(brief, self.beats, self.story)

    def test_enabled_only_allows_final_page_cta_and_disabled_rejects_tagged_leaks(self):
        enabled = compile_beats(self.brief, self.beats, self.story)
        self.assertTrue(cta_enabled(enabled))
        self.assertIn('exact approved storyboard CTA', page_prompt(enabled, enabled['pages'][-1]))
        for kind in ('keyword', 'narration'):
            brief, beats = self.without_cta()
            if kind == 'keyword':
                beats[-1]['panels'][-1]['texts'] = [{'type': 'keyword', 'text': '矢口乎搜「雨夜来信」'}]
            else:
                beats[-1]['strong_cta'] = True
            with self.assertRaisesRegex(ProductionError, '不加行动号召'):
                compile_beats(brief, beats, self.story)
        brief, beats = self.without_cta(); brief['cta']['enabled'] = True
        with self.assertRaisesRegex(ProductionError, '最后一张'):
            compile_beats(brief, beats, self.story)
        beats = copy.deepcopy(self.beats); beats[0]['strong_cta'] = True
        with self.assertRaisesRegex(ProductionError, '最后一张'):
            compile_beats(self.brief, beats, self.story)

    def test_cli_records_explicit_choice_without_loading_credentials(self):
        with patch.object(comic, 'load_env', side_effect=AssertionError('Offline init must not read keys')):
            for flag, expected in (('include', True), ('omit', False)):
                target = self.root/flag
                with patch('sys.stdout', new=io.StringIO()):
                    result = main(['init', '--title', '测试', '--style', 'chibi', '--final-cta', flag,
                                   '--base-url', 'https://images.example/v1', '--model', 'example-model',
                                   '--out', str(target)], legacy=comic)
                self.assertEqual(result, 0)
                self.assertIs(read_json(target/'brief.local.json')['cta']['enabled'], expected)

    def test_no_cta_preserves_story_page_count_and_full_album_timing(self):
        brief, beats = self.without_cta()
        p = compile_beats(brief, beats, self.story)
        self.assertEqual(len(p['pages']), 3)
        self.assertEqual(p['pages'][-1]['reader']['open'], beats[-1]['open'])
        for page in p['pages']:
            self.assertIn('No reader-directed call to action', page_prompt(p, page))
        report = pacing_report(p)
        self.assertFalse(report['cta_enabled'])
        self.assertEqual(report['reading_target_basis'], 'whole_album')
        self.assertIsNone(report['estimated_before_first_cta_seconds'])
        self.assertFalse(any('未识别到强CTA' in w for w in report['warnings']))
        self.assertEqual(report['estimated_total_seconds'], round(sum(x['estimated_seconds'] for x in report['pages']), 1))

    def test_legacy_plan_choice_is_not_retroactively_inferred(self):
        p = compile_beats(self.brief, self.beats, self.story)
        p['authoring_version'] = '3.4'; p.pop('cta')
        before = copy.deepcopy(p)
        validate_plan(p, self.story)
        self.assertIsNone(cta_enabled(p))
        self.assertEqual(before, p)

    def test_export_binds_actual_review_to_user_choice_for_every_page(self):
        brief, beats = self.without_cta()
        p = compile_beats(brief, beats, self.story)
        cfg = profile(); cfg['runtime'] = {'state_file': str(self.root/'state.sqlite3')}
        album_root = self.root/'album'
        with patch('comic_v3.provider.ImageProvider.generate', side_effect=AssertionError('No real API calls')):
            Production(p, cfg, self.story, album_root, comic, mock=True).run()
        manifest = read_json(album_root/'production.json'); manifest['mock'] = False
        write_json(album_root/'production.json', manifest)
        checks = ('source_fidelity', 'character_continuity', 'acting_composition', 'exact_text', 'reading_order', 'mobile_readability')
        review = {pid: {'sha256': page['sha256'], 'verdict': 'accepted', 'blocking_issues': [],
                       'checks': {key: True for key in checks}} for pid, page in manifest['pages'].items()}
        write_json(album_root/'visual-review.json', review)
        with self.assertRaisesRegex(ProductionError, '行动号召选择'):
            export(album_root)
        for entry in review.values():
            entry.update(cta_enabled=False, cta_notes='Synthetic fixture only, no real visual judgment.')
            entry['checks']['cta_choice'] = True
        write_json(album_root/'visual-review.json', review)
        images, _ = export(album_root)
        self.assertTrue(images.is_file())
        review[p['pages'][-1]['id']]['cta_enabled'] = True
        write_json(album_root/'visual-review.json', review)
        with self.assertRaisesRegex(ProductionError, '行动号召选择'):
            export(album_root)


if __name__ == '__main__':
    unittest.main()
