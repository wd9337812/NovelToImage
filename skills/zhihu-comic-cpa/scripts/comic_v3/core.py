from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


class ProductionError(Exception):
    """A short diagnostic safe to show without provider response bodies."""


def fingerprint(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def require(condition, message):
    if not condition:
        raise ProductionError(message)


def ident(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value), "ID需为安全、稳定的英文编号。")
    return value


def https_url(url, allow_query=False):
    p = urlsplit(url)
    require(p.scheme == "https" and p.hostname and not p.username and not p.password and not p.fragment,
            "服务端点需要不含凭据的HTTPS地址。")
    require(allow_query or not p.query, "服务端点不可含查询参数。")
    return url


def rectangle(box, label="区域"):
    require(isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box), f"{label}需为[x,y,w,h]。")
    x, y, w, h = box
    require(0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1.00001 and y + h <= 1.00001,
            f"{label}超出归一化画布。")
    return box


def overlap(a, b):
    return max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])) * max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))


def identity_bindings(plan, page, panel=None):
    cast = {c['id']: c for c in plan['characters']}
    result = {}
    for frame in [panel] if panel else page['panels']:
        for actor in frame.get('actors', []):
            key = (actor['character'], actor['version'])
            result[key] = {'character': key[0], 'version': key[1],
                           'assets': cast[key[0]]['reference_assets'][key[1]]}
    return list(result.values())


def reference_ids(plan, page, panel=None):
    ids = list(page.get('references', []))
    for binding in identity_bindings(plan, page, panel):
        ids.extend(binding['assets'])
    return sorted(set(ids))


def validate_plan(plan, story=None, title=None):
    require(plan.get("version") == 3, "v3分镜需要version: 3。旧分镜继续使用旧版入口。")
    keyword = plan.get("keyword")
    require(isinstance(keyword, str) and 0 < len(keyword.strip()) <= 64 and not any(ord(c) < 32 for c in keyword), "推广关键词为空或含控制字符。")
    require(title is None or title == keyword, "推广关键词须与输入标题逐字一致。")
    require(plan.get("mode") in {"promotion_excerpt", "full_adaptation", "style_pilot"}, "需声明改编范围模式。")
    require(bool(plan.get("style", {}).get("id")) and bool(plan["style"].get("prompt")), "缺少风格版本与可执行美术说明。")
    cast = plan.get("characters", [])
    require(bool(cast), "缺少人物身份表。")
    characters = {ident(c["id"]): c for c in cast}
    require(len(characters) == len(cast), "人物ID重复。")
    for person in cast:
        require(person.get("name") and person.get("appearance") and person.get("versions"), "人物需有身份锚点和状态版本。")
    all_ids = set(characters)
    used_versions = set()
    pages = plan.get("pages", [])
    require(bool(pages), "没有页面。")
    for page in pages:
        pid = ident(page["id"])
        require(pid not in all_ids, "页面ID重复。")
        all_ids.add(pid)
        require(page.get("purpose") and all(k in page.get("reader", {}) for k in ("known", "new", "open")), "逐页脚本需说明用途和读者信息。")
        require(page.get("route") in {"native_page", "page_art", "panels"}, "生成路线应为native_page/page_art/panels。")
        require(page.get("panels"), "每页需有具体分格脚本。")
        layout = page.get('layout', {})
        require(isinstance(layout.get('rationale'), str) and layout['rationale'].strip(), '每页需说明按剧情选择分格的layout.rationale。')
        require(layout.get('reading_order') == [p['id'] for p in page['panels']], 'layout.reading_order需与分镜顺序一致。')
        require(page.get("size", [1080, 1440])[0] >= 360, "页面尺寸过小。")
        regions = []
        for panel in page["panels"]:
            qid = ident(panel["id"])
            require(qid not in all_ids, "分格ID重复。")
            all_ids.add(qid)
            rectangle(panel["box"], "分格")
            require(all(overlap(panel['box'], other) < 1e-8 for other in regions), '分格区域重叠，请调整布局。')
            regions.append(panel['box'])
            require(panel.get("scene") and panel.get("action") and panel.get("emotion"), "分格需为可画的场景、单动作和情绪。")
            quote = panel.get("source_quote")
            require(isinstance(quote, str) and bool(quote), "分格缺少原文依据。")
            if story is not None:
                start = story.find(quote)
                require(start >= 0, f"{qid}的原文锚点不存在。")
                panel["source_span"] = {"start": start, "end": start + len(quote), "source_sha256": fingerprint(story.encode())}
            actors = panel.get("actors", [])
            ids = {a["character"] for a in actors}
            require(ids <= set(characters), "出现未定义角色。")
            for actor in actors:
                require(actor.get("version") in characters[actor["character"]]["versions"], "角色状态版本不存在。")
                used_versions.add((actor['character'], actor['version']))
                rectangle(actor["protect"], "人物保护区")
            for text in panel.get("texts", []):
                require(text.get("type") in {"dialogue", "thought", "narration", "sfx", "keyword"}, "未知文字功能。")
                require(isinstance(text.get("text"), str) and 0 < len(text["text"]) <= 500, "文字为空或过长，应拆分镜头。")
                rectangle(text["box"], "气泡")
                if "art_box" in text:
                    rectangle(text["art_box"], "原画保留区")
                if text["type"] in {"dialogue", "thought"}:
                    require(text.get("speaker") in ids, "对白说话者不在该格，画外音请明确改写为旁白。")
                    target = text.get("tail")
                    require(isinstance(target, list) and len(target) == 2 and all(0 <= v <= 1 for v in target), "对白需声明尾巴目标。")
                for actor in actors:
                    require(overlap(text["box"], actor["protect"]) == 0, f"{qid}气泡计划遮挡人物保护区，请先重排。")
                if text["type"] == "keyword":
                    require(keyword in text["text"], "尾页推广词不一致。")
    refs = plan.get("assets", [])
    for asset in refs:
        aid = ident(asset["id"])
        require(aid not in all_ids, "资产ID重复。")
        all_ids.add(aid)
        require(asset.get("prompt") or asset.get('local_path'), "资产需要生成说明或已有本地参考图local_path。")
    asset_ids = {a["id"] for a in refs}
    for asset in refs:
        require(set(asset.get("references", [])) <= asset_ids - {asset["id"]}, "资产参考缺失或自引用。")
    for page in pages:
        require(set(page.get("references", [])) <= asset_ids, "页面引用了未声明资产。")
    for cid, version in used_versions:
        refs = characters[cid].get('reference_assets', {}).get(version)
        require(isinstance(refs, list) and bool(refs) and set(refs) <= asset_ids,
                f'{cid}/{version}必须绑定已声明的人物参考图reference_assets，不能只用文字设定。')
    signatures = [fingerprint([p['box'] for p in page['panels']]) for page in pages]
    if len(pages) >= 3 and len(set(signatures)) == 1:
        require(bool(str(plan.get('layout_repetition_reason', '')).strip()),
                '全套重复同一布局，需按分镜调整或给出layout_repetition_reason；不能默认套上下两格。')
    return plan


def migrate_legacy(plan, story):
    """Preserve v1 text and IDs; explicit review is needed before modern rendering."""
    cast = [{**c, "versions": {"base": c["appearance"]}} for c in plan["characters"]]
    result = {"version": 3, "keyword": plan["title"], "mode": "promotion_excerpt",
              "style": {"id": "legacy-import", "prompt": "Retain existing character identity; modern narrative comic."},
              "characters": cast, "assets": [], "pages": []}
    for character in cast:
        aid = 'identity-'+character['id']
        character['reference_assets'] = {'base': [aid]}
        result['assets'].append({'id': aid, 'ratio': '4:3', 'prompt': f"Identity reference sheet for {character['name']}: {character['appearance']}. Consistent face, hair and clothing; no text."})
    for i, old in enumerate(plan["pages"], 1):
        page = {"id": f"page-{i:03d}", "route": "panels", "purpose": "迁移的原文连续事件，需复核节奏",
                "reader": {"known": "前页事实", "new": "本页原文事实", "open": "后续事件"}, "panels": []}
        for n, panel in enumerate(old["panels"]):
            actors = [{"character": c, "version": "base", "protect": [.25, .25, .5, .45]} for c in panel["characters"]]
            texts = []
            for j, t in enumerate(panel["texts"]):
                # Migration preserves old narration as narration; it cannot infer a correct bubble tail.
                texts.append({"type": "narration", "text": (t.get("speaker", "") + "：" if t["type"] == "dialogue" else "") + t["text"],
                              "box": [.03, .73 + j * .12, .94, .1]})
            page["panels"].append({"id": f"panel-{i:03d}-{n+1}", "box": [0, n/len(old["panels"]), 1, 1/len(old["panels"])],
                                   "scene": panel["scene"], "action": "保留原镜头动作", "emotion": "按原文复核",
                                   "source_quote": panel["source_quote"], "actors": actors, "texts": texts})
        result["pages"].append(page)
        page['layout'] = {'rationale': '保留原分镜几何供迁移；正式制作前按当前剧情重新导演。', 'reading_order': [p['id'] for p in page['panels']]}
    result['layout_repetition_reason'] = '历史分镜导入暂保留原布局，不代表已完成新版导演。'
    result["migration_note"] = "仅迁移正文；封面钩子、尾页悬念保留在legacy_metadata。未声称自动完成漫画改编。"
    result["legacy_metadata"] = {k: plan.get(k) for k in ("hook", "cliffhanger", "cover_scene", "post")}
    return validate_plan(result, story, plan["title"])
