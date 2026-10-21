import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/zhihu-comic-cpa/scripts'))
import comic
from comic_v3.authoring import chosen_style, compile_beats, initialize
from comic_v3.core import ProductionError, read_json
from comic_v3.pipeline import Production, page_prompt, export
from comic_v3.provider import validate_profile
from comic_v3.__main__ import main
from test_v3 import profile


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT/'runs'/'test-tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.tmp.name)
        refs = ROOT/'skills/zhihu-comic-cpa/references'
        self.brief = read_json(refs/'authoring-brief.example.json')
        self.beats = read_json(refs/'authoring-beats.example.json')['pages']
        self.story = (ROOT/'examples/story.txt').read_text(encoding='utf-8').strip()

    def tearDown(self):
        self.tmp.cleanup()

    def test_compile_preserves_source_dialogue_order_and_identity_bindings(self):
        p = compile_beats(self.brief, self.beats, self.story)
        self.assertEqual([x['id'] for x in p['pages']], ['page-001', 'page-002', 'page-003'])
        self.assertEqual([len(x['panels']) for x in p['pages']], [1, 3, 2])
        self.assertTrue(p['pacing']['enforce_page_range'])
        self.assertEqual(p['characters'][0]['reference_assets']['base'], ['ref-ning-base'])
        for beat, page in zip(self.beats, p['pages']):
            self.assertEqual([q['text'] for s in beat['panels'] for q in s['texts']],
                             [q['text'] for s in page['panels'] for q in s['texts']])
            for shot in page['panels']:
                span = shot['source_span']
                self.assertEqual(self.story[span['start']:span['end']], shot['source_quote'])

    def test_standard_and_chibi_prompts_and_reference_art_share_choice(self):
        for style in ('standard', 'chibi'):
            brief = copy.deepcopy(self.brief); brief['style'] = {'mode': style}
            p = compile_beats(brief, self.beats, self.story)
            root = self.root/style
            cfg = profile(); cfg['runtime'] = {'state_file': str(root/'state.sqlite3')}
            with patch('comic_v3.provider.ImageProvider.generate', side_effect=AssertionError('No live API allowed')):
                Production(p, cfg, self.story, root, comic, mock=True).run()
            asset = (root/'prompts/ref-ning-base.md').read_text(encoding='utf-8')
            page = (root/'prompts/page-001.md').read_text(encoding='utf-8')
            self.assertIn(p['style']['prompt'], asset)
            self.assertIn(p['style']['prompt'], page)
            self.assertIn('natural-proportion' if style == 'standard' else 'three-head-tall', page)
            self.assertNotIn('Keep the established chibi drawing proportions', page)
            self.assertTrue((root/'images/01-page-001.png').is_file())
            image_zip, trace = export(root)
            self.assertTrue(image_zip.name.startswith('MOCK-'))
            self.assertTrue(trace.is_file())

    def test_legacy_custom_style_has_no_forced_chibi_proportion(self):
        p = compile_beats(self.brief, self.beats, self.story)
        p['style'] = {'id': 'old-ink', 'prompt': 'Natural proportion black ink comic.'}
        self.assertNotIn('chibi', page_prompt(p, p['pages'][0]).lower())
        p['style'] = chosen_style('custom', 'Watercolor, natural proportions, delicate ink outlines.')
        self.assertIn('Watercolor', page_prompt(p, p['pages'][0]))

    def test_initialization_needs_research_and_cannot_store_key(self):
        target = self.root/'new'
        initialize('测试标题', 'standard', 'https://images.example/v1/', 'example-image', target)
        saved = read_json(target/'provider-profile.local.json')
        self.assertEqual(saved['base_url'], 'https://images.example/v1')
        self.assertEqual(saved['api_key_env'], 'IMAGE_API_KEY')
        self.assertFalse((target/'.env').exists())
        with self.assertRaises(ProductionError): validate_profile(saved)
        before = (target/'brief.local.json').read_bytes()
        with self.assertRaises(ProductionError):
            initialize('另一个标题', 'chibi', 'https://images.example/v1', 'example-image', target)
        self.assertEqual((target/'brief.local.json').read_bytes(), before)
        for url, env in [('https://images.example/v1?key=fake', 'IMAGE_API_KEY'),
                         ('https://images.example/v1', 'sk-fake')]:
            with self.assertRaises(ProductionError):
                initialize('标题', 'standard', url, 'example-image', self.root/'bad', env)
            self.assertFalse((self.root/'bad').exists())

    def test_compile_stops_missing_source_speaker_count_and_long_text(self):
        for case in ('source', 'speaker', 'page_count', 'text', 'layout'):
            brief = copy.deepcopy(self.brief); beats = copy.deepcopy(self.beats)
            shot = beats[0]['panels'][0]
            if case == 'source': shot['quote'] = '原文没有这件事'
            elif case == 'speaker': shot['texts'][0] = {'type': 'dialogue', 'speaker': 'ghost', 'text': '谁在那里？'}
            elif case == 'page_count': brief['page_count'] = 100
            elif case == 'text': shot['texts'][0]['text'] = '字'*49
            else: beats[0]['layout'] = 'quad'
            with self.assertRaises(ProductionError): compile_beats(brief, beats, self.story)

    def test_wardrobe_reference_depends_on_original_identity(self):
        self.brief['characters'][0]['versions']['night'] = 'plain ivory nightwear'
        p = compile_beats(self.brief, self.beats, self.story)
        self.assertEqual(p['assets'][1]['references'], ['ref-ning-base'])
        self.assertEqual(p['characters'][0]['reference_assets']['night'], ['ref-ning-night'])

    def test_cli_merges_batches_in_explicit_order_without_api_or_env_read(self):
        brief_path = self.root/'brief.local.json'; brief_path.write_text(json.dumps(self.brief), encoding='utf-8')
        story_path = self.root/'story.txt'; story_path.write_text(self.story, encoding='utf-8')
        a = self.root/'z-first.json'; a.write_text(json.dumps({'pages': self.beats[:1]}), encoding='utf-8')
        b = self.root/'a-next.json'; b.write_text(json.dumps({'pages': self.beats[1:]}), encoding='utf-8')
        out = self.root/'plan.json'
        with patch.object(comic, 'load_env', side_effect=AssertionError('Offline compile needs no credentials')):
            with patch('sys.stdout', new=io.StringIO()):
                rc = main(['compile', '--brief', str(brief_path), '--beats', str(a), str(b),
                           '--story', str(story_path), '--out', str(out)], legacy=comic)
        self.assertEqual(rc, 0)
        self.assertEqual(read_json(out)['pages'][0]['purpose'], self.beats[0]['purpose'])


if __name__ == '__main__':
    unittest.main()
