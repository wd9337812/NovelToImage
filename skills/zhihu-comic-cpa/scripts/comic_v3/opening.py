"""Social-story opening planning and evidence-bound review; no retention scoring."""
from __future__ import annotations

import re

from .core import fingerprint, read_json, require, reference_ids


OPENING_CHECKS = (
    'context_clear', 'conflict_visible', 'information_progress',
    'page_two_payoff', 'mobile_readability', 'source_fidelity',
)


def social_opening(plan):
    return plan.get('opening', {}).get('scope') == 'social_story'


def text_count(page):
    visible = ''.join(t['text'] for p in page['panels'] for t in p.get('texts', [])
                      if t['type'] != 'keyword')
    return len(re.sub(r'\s+', '', visible))


def strong_cta(page):
    return page.get('strong_cta') is True or any(
        t['type'] == 'keyword' for p in page['panels'] for t in p.get('texts', []))


def _text(value, label):
    require(isinstance(value, str) and bool(value.strip()), label+'需填写具体内容。')


def _anchor(value, story, label):
    _text(value, label)
    if story is not None:
        require(value in story, label+'的原文锚点不存在。')


def validate_opening(plan, story=None):
    opening = plan.get('opening')
    modern_promotion = plan.get('authoring_version') == '3.4' and plan['mode'] == 'promotion_excerpt'
    if opening is None:
        require(not modern_promotion, 'v3.4社媒推广需先填写opening开场策略，不能直接批量生图。')
        return
    require(isinstance(opening, dict) and opening.get('version') == 1, 'opening需要version:1。')
    scope = opening.get('scope')
    require(scope in {'social_story', 'user_requested_cover', 'not_social'}, 'opening.scope无效。')
    if scope != 'social_story':
        _text(opening.get('reason'), '开场豁免理由')
        _text(opening.get('user_instruction'), '非社媒／独立封面的用户要求')
        return
    require(len(plan['pages']) >= 3, '社媒开场需规划连续前三张；短试样请明确使用style_pilot。')
    candidates = opening.get('candidates')
    require(isinstance(candidates, list) and len(candidates) == 3, '先写三个文字开场候选，不需要三套付费样图。')
    ids = []
    for candidate in candidates:
        require(isinstance(candidate, dict), '开场候选需为对象。')
        for key in ('id', 'approach', 'summary', 'next_page'):
            _text(candidate.get(key), '开场候选'+key)
        _anchor(candidate.get('source_quote'), story, '开场候选')
        ids.append(candidate['id'])
    require(len(set(ids)) == 3 and opening.get('selected') in ids, '开场候选ID需唯一，并选择一个selected。')
    _text(opening.get('selection_reason'), '开场选择理由')
    records = opening.get('pages')
    first = plan['pages'][:3]
    require(isinstance(records, list) and len(records) == 3
            and [r.get('page_id') for r in records] == [p['id'] for p in first],
            'opening.pages需依次对应最终计划前三张的实际ID。')
    for index, (record, page) in enumerate(zip(records, first)):
        for key in ('new_fact', 'visible_evidence', 'unresolved', 'next_page_bridge'):
            _text(record.get(key), '开场第'+str(index+1)+'张'+key)
        _anchor(record.get('source_quote'), story, '开场页面')
        require(record.get('beat') in {'setup_only', 'conflict', 'evidence', 'reaction', 'decision'}, '开场beat类型无效。')
        if index == 0:
            require(record['beat'] != 'setup_only', '首张仅介绍背景，需先改为有具体矛盾的剧情开场。')
        require(not strong_cta(page), '社媒前三张先兑现剧情，不放强CTA。')
    if len(first[0]['panels']) == 1:
        _text(opening.get('single_panel_reason'), '单格首张如何同时呈现关系、冲突与行动')


def opening_report(plan):
    """An audit aid, including legacy diagnostics; never claims semantic approval."""
    config = plan.get('opening', {})
    active = social_opening(plan)
    pages = [{'id': p['id'], 'panels': len(p['panels']), 'characters': text_count(p),
              'has_strong_cta': strong_cta(p), 'purpose': p['purpose'], 'reader': p['reader']}
             for p in plan['pages'][:3]]
    warnings = []
    if not config:
        warnings.append('旧计划未按v3.4开场标准复核；不自动迁移、补审或重画。')
    if pages[0]['panels'] == 1:
        warnings.append('首张为单格：实际检查是否只有立绘配介绍；有理由不等于已通过。')
    if pages[0]['characters'] < 45:
        warnings.append('首张文字少于45字：检查画面是否已提供足够事件信息，不为凑字数添加旁白。')
    elif pages[0]['characters'] > 85:
        warnings.append('首张文字超过85字：检查手机可读性，优先精简或调整版式，不缩字号。')
    if any(p['has_strong_cta'] for p in pages):
        warnings.append('前三张出现强CTA；社媒开场应先兑现剧情。')
    return {'status': 'requires_actual_review' if active else 'scope_exempt' if config else 'legacy_not_assessed',
            'scope': config.get('scope'), 'required_review': active,
            'plan_hash': opening_binding(plan) if active else None,
            'basis': 'Editorial planning only; no measured retention, conversion or automatic semantic judgment.',
            'first_page_character_reference': [45, 85], 'pages': pages, 'warnings': warnings}


def opening_binding(plan):
    # Subsequent pages can change without invalidating a completed opening review.
    first = plan['pages'][:3]
    cast_ids = {a['character'] for p in first for panel in p['panels'] for a in panel.get('actors', [])}
    asset_ids = {aid for p in first for aid in reference_ids(plan, p)}
    assets = {a['id']: a for a in plan.get('assets', [])}
    pending = list(asset_ids)
    while pending:
        for aid in assets[pending.pop()].get('references', []):
            if aid not in asset_ids:
                asset_ids.add(aid)
                pending.append(aid)
    return fingerprint({'opening': plan['opening'], 'pages': plan['pages'][:3],
                        'style': plan['style'], 'keyword': plan['keyword'], 'mode': plan['mode'],
                        'characters': [c for c in plan['characters'] if c['id'] in cast_ids],
                        'assets': [a for a in plan.get('assets', []) if a['id'] in asset_ids]})


def opening_review_issues(plan, manifest, root):
    """Check review provenance and images, not whether the supplied verdict is true."""
    if not social_opening(plan):
        return []
    path = root/'opening-review.json'
    if not path.is_file():
        return ['缺少opening-review.json；需实际看前三张并完成开场专项审查。']
    review = read_json(path)
    issues = []
    reviewer = review.get('reviewer')
    if (review.get('plan_hash') != opening_binding(plan) or review.get('verdict') != 'accepted'
            or review.get('blocking_issues') != [] or not isinstance(reviewer, str) or not reviewer.strip()):
        issues.append('开场策略／分镜已变或专项审查未通过。')
    for key in OPENING_CHECKS:
        observation = review.get('observations', {}).get(key)
        if review.get('checks', {}).get(key) is not True or not isinstance(observation, str) or not observation.strip():
            issues.append('开场检查缺少实际观察或未通过：'+key)
    for page in plan['pages'][:3]:
        pid = page['id']
        info = manifest.get('pages', {}).get(pid, {})
        image = root/info.get('file', '__missing__')
        if (not info.get('sha256') or review.get('page_hashes', {}).get(pid) != info['sha256']
                or info.get('page_spec_hash') != fingerprint(page)
                or not image.is_file() or fingerprint(image.read_bytes()) != info['sha256']):
            issues.append('开场图缺失／已改变，需重新审查：'+pid)
    return issues
