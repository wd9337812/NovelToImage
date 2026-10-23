"""Transparent storyboard reading-time estimate, not measured viewer retention."""
from __future__ import annotations

import re

from .core import require
from .cta import cta_enabled, has_cta


def pacing_report(plan):
    config = plan.get('pacing', {})
    enabled = cta_enabled(plan)
    cps = config.get('characters_per_second', 7.5)
    panel_seconds = config.get('seconds_per_panel', 2.0)
    turn = config.get('page_turn_seconds', .5)
    require(isinstance(cps, (int, float)) and cps > 0, '阅读速度需为正数。')
    require(isinstance(panel_seconds, (int, float)) and panel_seconds > 0, '看格时间需为正数。')
    require(isinstance(turn, (int, float)) and turn >= 0, '翻页时间不能为负数。')
    long_promotion = plan.get('mode') == 'promotion_excerpt'
    target = config.get('target_seconds', [360, 1200] if long_promotion else [90, 150])
    require(isinstance(target, list) and len(target) == 2 and 0 < target[0] <= target[1], '阅读时长目标需为正数区间。')
    page_target = config.get('target_page_count', [60, 100] if long_promotion else None)
    if page_target is not None:
        require(isinstance(page_target, list) and len(page_target) == 2 and all(isinstance(n, int) for n in page_target)
                and 1 <= page_target[0] <= page_target[1], '目标张数需为正整数区间。')
    pages = []
    elapsed = 0
    first_cta = None
    for page in plan['pages']:
        texts = [t for p in page['panels'] for t in p.get('texts', [])]
        marked_cta = has_cta(page)
        if marked_cta and first_cta is None:
            # Conservatively exclude the entire CTA page from the prior reading time.
            first_cta = elapsed
        visible = ''.join(t['text'] for t in texts if t['type'] != 'keyword')
        count = len(re.sub(r'\s+', '', visible))
        seconds = max(count/cps, len(page['panels'])*panel_seconds) + turn
        elapsed += seconds
        pages.append({'id': page['id'], 'characters': count, 'panels': len(page['panels']),
                      'estimated_seconds': round(seconds, 1), 'has_strong_cta': marked_cta})
    before = elapsed if first_cta is None else first_cta
    warnings = []
    if page_target and not page_target[0] <= len(pages) <= page_target[1]:
        warnings.append('计划张数不在目标区间；核对用户长图集要求，不得以短试样冒充完整交付。')
    if before < target[0]:
        warnings.append(('整套正文' if enabled is False else '首个强CTA前')+'的估计阅读时长不足；补充有原文依据的因果、行动与情绪推进，勿复制页面或灌水。')
    if before > target[1]:
        warnings.append('估计时长超过目标；检查信息重复，或按渠道张数限制拆成各自完整的连续篇章。')
    if first_cta is None and enabled is not False:
        warnings.append('未识别到强CTA；文字为narration时请在页面显式标记strong_cta。')
    return {'method': 'max(visible characters / cps, panels * seconds_per_panel) + page_turn; CTA page excluded from prior time',
            'basis': 'Editorial planning heuristic; no measured retention or conversion claim.',
            'assumptions': {'characters_per_second': cps, 'seconds_per_panel': panel_seconds, 'page_turn_seconds': turn},
            'target_seconds': target, 'target_page_count': page_target, 'page_count': len(pages),
            'cta_enabled': enabled, 'reading_target_basis': 'whole_album' if enabled is False else 'before_first_cta',
            'total_characters': sum(p['characters'] for p in pages),
            'total_panels': sum(p['panels'] for p in pages),
            'estimated_total_seconds': round(elapsed, 1),
            'estimated_before_first_cta_seconds': None if enabled is False else round(before, 1),
            'warnings': warnings, 'pages': pages}
