"""Offline authoring aids. No credentials, API calls, or automatic visual approval."""
from __future__ import annotations

import copy
from pathlib import Path
import re

from .core import ident, read_json, require, validate_plan, write_json, https_url

STYLES = {
    'chibi': {
        'label': 'Q版漫画',
        'prompt': 'Original chibi narrative comic. Consistent approximately three-head-tall stylized proportions, large expressive eyes, clean fine ink lines, soft cel shading, detailed but uncluttered environments. Preserve documented ages and distinguish children from adults through facial structure, stature and clothing. Clear emotional acting; no reference-sheet insets in story scenes.',
        'continuity': 'Keep the chosen chibi head-to-body proportions consistent across the cast; preserve their documented ages.',
    },
    'standard': {
        'label': '非Q版漫画',
        'prompt': 'Original natural-proportion narrative comic. Age-appropriate human anatomy; adults approximately six-and-a-half to seven-and-a-half heads tall, children proportioned for their documented age. Moderately sized expressive eyes, clean fine ink lines, soft cel shading, detailed but uncluttered environments. No chibi, super-deformed bodies, oversized heads, doll anatomy or baby faces on adult characters. Clear emotional acting.',
        'continuity': 'Keep natural, age-appropriate human proportions consistent across the cast. Do not turn this into chibi or super-deformed art.',
    },
}

# Coordinates are authoring seeds, never evidence that the generated image obeyed them.
LAYOUTS = {
    'hero': [[0, 0, 1, 1]],
    'duo_rows': [[0, 0, 1, .49], [0, .51, 1, .49]],
    'duo_columns': [[0, 0, .49, 1], [.51, 0, .49, 1]],
    'lead_two': [[0, 0, 1, .49], [0, .51, .49, .49], [.51, .51, .49, .49]],
    'two_lead': [[0, 0, .49, .49], [.51, 0, .49, .49], [0, .51, 1, .49]],
    'quad': [[0, 0, .49, .49], [.51, 0, .49, .49], [0, .51, .49, .49], [.51, .51, .49, .49]],
}


def chosen_style(mode, custom_prompt=None):
    require(mode in {*STYLES, 'custom'}, '风格请选择chibi（Q版）、standard（非Q版）或custom。')
    if mode == 'custom':
        require(isinstance(custom_prompt, str) and custom_prompt.strip(), '自定义风格需要具体比例、线条与着色说明。')
        prompt = custom_prompt.strip()
    else:
        prompt = STYLES[mode]['prompt']
    return {'id': 'v33-'+mode, 'mode': mode, 'prompt': prompt}


def proportion_instruction(style):
    return STYLES.get(style.get('mode'), {}).get('continuity',
        'Keep the documented drawing proportions consistent across all cast members; follow the selected art direction.')


def initialize(title, mode, base_url, model, out, api_key_env='IMAGE_API_KEY', custom_prompt=None):
    """Create an intentionally unverified local profile; never accept a literal key."""
    require(isinstance(title, str) and title.strip() and len(title) <= 64, '需要准确标题，最多64字。')
    https_url(base_url)
    require(bool(model.strip()), '需要服务商的精确模型名称。')
    require(re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', api_key_env) is not None, 'Key只填写环境变量名，例如IMAGE_API_KEY。')
    require(not model.startswith('sk-'), '模型名不能填写Key。')
    style = chosen_style(mode, custom_prompt)
    out = Path(out)
    require(not out.exists(), '项目目录已存在；请继续编辑已有项目，或选择新的目录，不能覆盖。')
    template = Path(__file__).resolve().parents[2]/'provider-profile.template.json'
    profile = read_json(template)
    profile.update(base_url=base_url.rstrip('/'), model=model, api_key_env=api_key_env)
    brief = {'keyword': title, 'mode': 'promotion_excerpt', 'style': style,
             'characters': [], 'page_count': None,
             'pacing': {'target_page_count': [60, 100], 'target_seconds': [360, 1200]}}
    write_json(out/'brief.local.json', brief)
    write_json(out/'provider-profile.local.json', profile)
    write_json(out/'beats.json', {'pages': []})
    (out/'.env.example').write_text(api_key_env+'=\n', encoding='utf-8')
    return out


def compile_beats(brief, pages, story):
    """Compile a compact storyboard into a validated v3 plan. Fail before network use."""
    require(isinstance(brief, dict) and isinstance(pages, list) and pages, '简化分镜需要非空pages数组。')
    selection = brief.get('style', {})
    if isinstance(selection, str):
        selection = {'mode': selection}
    style = chosen_style(selection.get('mode'), selection.get('prompt'))
    result = {'version': 3, 'keyword': brief['keyword'], 'mode': brief.get('mode', 'promotion_excerpt'),
              'style': style, 'characters': [], 'assets': [], 'pages': [],
              'pacing': copy.deepcopy(brief.get('pacing', {}))}
    if brief.get('page_count') is not None:
        count = brief['page_count']
        require(type(count) is int and count > 0, 'page_count需为正整数，未定数量用null。')
        result['pacing'].update(target_page_count=[count, count], enforce_page_range=True)
    if brief.get('layout_repetition_reason'):
        result['layout_repetition_reason'] = brief['layout_repetition_reason']
    cast = {}
    for original in brief.get('characters', []):
        char = copy.deepcopy(original)
        cid = ident(char['id'])
        require(cid not in cast and char.get('name') and char.get('appearance'), '人物ID重复或缺少名字、外观锚点。')
        versions = char.get('versions')
        require(isinstance(versions, dict) and versions, '人物需要versions，例如base对应固定服装。')
        char['reference_assets'] = {}
        first = None
        for version, clothing in versions.items():
            ident(version)
            aid = ident(f'ref-{cid}-{version}')
            spec = {'id': aid, 'ratio': '3:4', 'prompt':
                f'ONE single-view identity portrait of {char["name"]} ({cid}). {char["appearance"]}. Wardrobe: {clothing}. '
                'Three-quarter standing view, clear face and distinctive hair, hands visible, neutral simple background. '
                'One person only, no duplicate heads, no inset portraits, no sheet grid, no captions or text. '
                'This is the fixed identity for the story, not a story panel.'}
            local = char.get('reference_paths', {}).get(version)
            if local:
                spec['local_path'] = local
            elif first:
                spec['references'] = [first]
                spec['prompt'] += ' Preserve the attached person identity, change only this documented wardrobe/state.'
            first = first or aid
            result['assets'].append(spec)
            char['reference_assets'][version] = [aid]
        char.pop('reference_paths', None)
        cast[cid] = char
        result['characters'].append(char)
    for i, beat in enumerate(pages, 1):
        pid = beat.get('id', f'page-{i:03}')
        layout = beat.get('layout')
        require(layout in LAYOUTS or layout == 'custom', f'{pid}需选择有效layout。')
        shots = beat.get('panels', [])
        boxes = beat.get('boxes') if layout == 'custom' else LAYOUTS[layout]
        require(isinstance(boxes, list) and len(shots) == len(boxes) and shots, f'{pid}格数与layout不一致。')
        require(beat.get('why'), f'{pid}缺少选择此分格的具体why。')
        page = {'id': pid, 'label': beat.get('label', f'{i:03}'), 'route': 'page_art',
                'output_policy': 'follow_art_aspect', 'compact_lettering': True,
                'size': [1080, 1440], 'purpose': beat['purpose'],
                'reader': {key: beat[key] for key in ('known', 'new', 'open')},
                'layout': {'rationale': beat['why'], 'reading_order': []}, 'panels': []}
        if beat.get('strong_cta'):
            page['strong_cta'] = True
        for j, (shot, box) in enumerate(zip(shots, boxes), 1):
            qid = f'{pid}-p{j}'
            actors = []
            names = shot.get('cast', [])
            require(len(names) <= 2 and len(names) == len(set(names)), f'{qid}简化入口每格最多两位角色；群像请拆反应镜头或使用完整v3分镜。')
            for k, name in enumerate(names):
                parts = name.split(':')
                require(len(parts) == 2, f'{qid}cast使用角色ID:版本。')
                cid, version = parts
                require(cid in cast and version in cast[cid]['versions'], f'{qid}角色或版本未定义。')
                w = .90/len(names)
                actors.append({'character': cid, 'version': version,
                    'protect': [.05+k*w, .43, w-.025, .53],
                    'blocking': f'Place this character in position{k+1} from left; face and hands below top43% reserved text area. Preserve fixed identity. Do not copy reference pose/background.'})
            texts = copy.deepcopy(shot.get('texts', []))
            require(len(texts) <= 2, f'{qid}文字过多，请拆镜头；简化入口每格最多两个文字框。')
            for k, text in enumerate(texts):
                require(len(text.get('text', '').replace('\n', '')) <= (24 if len(texts) == 2 else 48),
                        f'{qid}单格文字偏长，先精简或拆镜头，不缩小手机字号。')
                text['box'] = ([.035, .025, .93, .36] if len(texts) == 1 else [.035+.48*k, .025, .45, .36])
                if text.get('type') in ('dialogue', 'thought'):
                    speakers = [a['character'] for a in actors]
                    require(text.get('speaker') in speakers, f'{qid}对白说话者必须在本格cast内。')
                    x = .05+(speakers.index(text['speaker'])+.5)*(.90/len(actors))
                    text['tail'] = [round(x, 4), .435]
            panel = {'id': qid, 'box': copy.deepcopy(box), 'source_quote': shot['quote'],
                     'scene': shot['scene'], 'action': shot['action'], 'emotion': shot['emotion'],
                     'actors': actors, 'texts': texts}
            page['panels'].append(panel)
            page['layout']['reading_order'].append(qid)
        result['pages'].append(page)
    return validate_plan(result, story, brief['keyword'])
