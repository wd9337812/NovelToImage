"""Explicit final-page CTA choice; semantic and image compliance still need review."""
from .core import require


def cta_enabled(plan):
    return plan.get('cta', {}).get('enabled')


def has_cta(page):
    return page.get('strong_cta') is True or any(
        t['type'] == 'keyword' for p in page['panels'] for t in p.get('texts', []))


def validate_cta(plan):
    config = plan.get('cta')
    if config is None:
        require(plan.get('authoring_version') != '3.5', 'v3.5需先询问末张是否需要行动号召，填写cta.enabled。')
        return
    require(isinstance(config, dict) and type(config.get('enabled')) is bool,
            '末张行动号召尚未选择：cta.enabled必须为true或false，不能把未回答当成选择。')
    marked = [i for i, page in enumerate(plan['pages']) if has_cta(page)]
    if not config['enabled']:
        require(not marked, '已选择不加行动号召，需移除全部强CTA标记及keyword引导文字，保留剧情悬念。')
    else:
        require(marked == [len(plan['pages'])-1], '已选择末张行动号召：仅最后一张应包含明确标记的CTA。')


def cta_instruction(plan, page):
    enabled = cta_enabled(plan)
    if enabled is None:
        return ''
    if not enabled or page['id'] != plan['pages'][-1]['id']:
        return ('No reader-directed call to action: no requests to search a platform or book title, '
                'click a link, visit a profile, send a message, follow, like, comment or scan a QR code. '
                'Do not invent promotional text. Draw only the source-backed story, ending with its unresolved event when appropriate.')
    return 'On this final page, include only the exact approved storyboard CTA; do not invent extra promotional text, links or QR codes.'
