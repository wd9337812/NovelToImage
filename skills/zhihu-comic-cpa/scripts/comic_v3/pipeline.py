from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import copy
import io
import json
from pathlib import Path
import zipfile

from PIL import Image

from . import VERSION
from .core import ProductionError, require, fingerprint, read_json, write_json, atomic_write, validate_plan, reference_ids, identity_bindings
from .provider import ImageProvider, validate_profile
from .render import Letterer, contact_sheet, layout_preview
from .scheduler import Scheduler


def aspect(width, height, supported):
    def error(ratio):
        a, b = map(float, ratio.split(":"))
        return abs(a/b-width/height)
    require(bool(supported), "请查资料配置支持的宽高比。")
    return min(supported, key=error)


def page_prompt(plan, page, only_panel=None):
    native = page["route"] == "native_page" and only_panel is None
    no_text = not native
    opening = "Create ONE original narrative comic illustration, a single wide scene with no grid or inset portraits." if only_panel else "Create an original finished narrative comic, portrait page."
    chunks = [f"{opening} {plan['style']['prompt']}",
              "Art direction and acting must be coherent across this story. Adult characters remain adults. Detailed lived-in backgrounds with controlled light; varied intentional camera staging.",
              f"Page dramatic purpose: {page['purpose']}. Read left-to-right, top-to-bottom. Thin clean white gutters. Fill the canvas with story art, no slide header, no large footer caption strips, no blank poster margins."]
    chunks.append(f"Storyboard layout rationale: {page['layout']['rationale']}. Exact panel count: {1 if only_panel else len(page['panels'])}. Follow specified panel rectangles and reading order, not a default two-strip page.")
    chunks.append('Identity reference mapping: '+json.dumps(identity_bindings(plan, page, only_panel), ensure_ascii=False))
    chunks.append('Input reference order: '+', '.join(reference_ids(plan, page, only_panel)))
    characters = {c["id"]: c for c in plan["characters"]}
    panels = [only_panel] if only_panel else page["panels"]
    for number, panel in enumerate(panels, 1):
        chunks.append(f"PANEL {number}. Relative [left,top,width,height]={panel['box'] if not only_panel else [0,0,1,1]}. Scene: {panel['scene']}. Single frozen action: {panel['action']}. Emotional acting: {panel['emotion']}.")
        for actor in panel["actors"]:
            char = characters[actor["character"]]
            chunks.append(f"Character {char['name']} ({char['id']}), wardrobe {actor['version']}: {char['appearance']}; {char['versions'][actor['version']]}. Blocking: {actor.get('blocking','use deliberate composition')}. Protect face and key action region {actor['protect']}.")
        for text in panel.get("texts", []):
            if native:
                speaker = characters.get(text.get("speaker"), {}).get("name", "narrator")
                chunks.append(f"Letter exactly this Simplified Chinese text ONCE, in reading order, {text['type']} for {speaker}: 「{text['text']}」. Approximate bubble box within panel={text['box']}; tail points to {text.get('tail','no tail')}. White bubble with dark thin outline; readable dark lettering; size fits content; do not obscure faces or gestures.")
            else:
                chunks.append(f"Reserve quiet low-detail negative space at {text.get('art_box', text['box'])} within this panel for later typesetting; draw no bubble outline and absolutely no words in that zone.")
    if native:
        chunks.append(f"Small unobtrusive page label: {plan['keyword']} · {page.get('label',page['id'])}. Small bottom credit: AI辅助创作. All dialogue must belong to its named speaker. No other letters, captions, watermarks, UI, or invented lines.")
    else:
        chunks.append("NO text, letters, numbers, speech bubbles, captions, labels, watermarks or user-interface. This is an image layer, not a placeholder graphic.")
    if only_panel:
        chunks.append("Draw this ONE scene as a single coherent illustration, not a multi-panel page. Use the entire requested canvas and the reserved text areas.")
    chunks.append("Identity reference images are mandatory for every depicted cast member. Preserve their exact face, hair, adult identity and wardrobe. Use references for identity only; do not copy the reference-sheet grid, poses, background or panel count. Keep adult chibi proportions consistent across all cast members.")
    return "\n\n".join(chunks)


class Production:
    def __init__(self, plan, profile, story, root, legacy, budget=12, mock=False, transport=None, asset_base=None):
        self.plan = validate_plan(copy.deepcopy(plan), story)
        self.profile = validate_profile(profile)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.asset_base = Path(asset_base or Path.cwd())
        self.legacy, self.mock = legacy, mock
        state_file = profile.get("runtime", {}).get("state_file", str(Path.cwd()/"runs/.cache/v3-scheduler.sqlite3"))
        self.scheduler = Scheduler(state_file, profile, fingerprint(str(self.root.resolve()))[:20], budget)
        self.provider = ImageProvider(profile, self.scheduler, legacy, transport=transport)
        self.manifest_path = self.root/"production.json"
        self.manifest = read_json(self.manifest_path) if self.manifest_path.is_file() else {"version": VERSION, "jobs": {}, "pages": {}}
        self.manifest.update(keyword=plan["keyword"], mode=plan["mode"], mock=mock, status="in_progress")
        self.manifest['identity_contract'] = 'required-v1'
        self.manifest["planned_page_ids"] = [p["id"] for p in self.plan["pages"]]
        current_specs = {p["id"]: fingerprint(p) for p in self.plan["pages"]}
        self.manifest["pages"] = {pid: info for pid, info in self.manifest["pages"].items()
                                  if info.get("page_spec_hash") == current_specs.get(pid)}
        (self.root/"images").mkdir(exist_ok=True)
        (self.root/"prompts").mkdir(exist_ok=True)
        self.cache = self.root.parent/".cache"/"v3-art"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.refs = {}
        self.raws = {}
        self.errors = []
        self.font = legacy.font_path(legacy.load_config())

    def image(self, unit, prompt, ratio, references, phase):
        key = fingerprint({"model": self.profile["model"], "endpoint": self.profile["base_url"],
                           "protocol": self.profile["protocol"], "resolution": self.profile.get("resolution"),
                           "style": self.plan["style"], "prompt": prompt, "ratio": ratio,
                           "references": [fingerprint(Path(p).read_bytes()) for p in references], "mock": self.mock})
        path = self.cache/(key+".png")
        atomic_write(self.root/"prompts"/(unit+".md"), prompt.encode())
        record = {"cache_key": key, "phase": phase, "ratio": ratio, "prompt": "prompts/"+unit+".md",
                  "references": [{"sha256": fingerprint(Path(p).read_bytes())} for p in references],
                  "actual_reference_count": len(references), "status": "pending"}
        if path.is_file():
            with Image.open(path) as existing:
                existing.verify()
            raw = path.read_bytes()
            record["reused"] = True
        elif self.mock:
            a, b = map(int, ratio.split(":"))
            canvas = Image.new("RGB", (864, round(864*b/a)), "#e5ecf1")
            from PIL import ImageDraw, ImageFont
            ImageDraw.Draw(canvas).text((35, 50), "MOCK\n离线排版预览", font=ImageFont.truetype(self.font, 42), fill="#394754")
            buf = io.BytesIO(); canvas.save(buf, format="PNG"); raw = buf.getvalue()
            atomic_write(path, raw)
        else:
            print(f"生成 {unit}；画幅{ratio}；参考图{len(references)}张", flush=True)
            raw = self.provider.generate(key, prompt, ratio, references)
            atomic_write(path, raw)
        record.update(status="generated_unreviewed", sha256=fingerprint(raw), cache_file=path.name)
        return unit, raw, path, record

    def run(self, selected=None, stage="all"):
        pages = [p for p in self.plan["pages"] if not selected or p["id"] in selected]
        require(bool(pages), "未找到所选页面。")
        layout_preview({**self.plan, 'pages': pages}, self.root/'layouts', self.font)
        needed = set(r for p in pages for r in reference_ids(self.plan, p))
        require(not needed or self.profile['capabilities'].get('references') is True,
                '当前模型未核验参考图能力，不能生成有角色的漫画；请查资料修复适配，禁止无参考降级。')
        assets = {a["id"]: a for a in self.plan.get("assets", [])}
        if stage == "assets":
            needed = set(assets)
        def collect(aid, trail=()):
            require(aid not in trail, "资产依赖形成循环。")
            for parent in assets[aid].get("references", []):
                needed.add(parent)
                collect(parent, (*trail, aid))
        for aid in list(needed):
            collect(aid)
        def reviewed(aid):
            if self.mock:
                return
            review_file = self.root/'asset-review.json'
            review = read_json(review_file) if review_file.is_file() else {}
            entry = review.get(aid, {})
            if not (entry.get('accepted') is True and entry.get('sha256') == fingerprint(self.refs[aid].read_bytes())):
                self.manifest['status'] = 'awaiting_asset_review'
                self.save()
                raise ProductionError('人物参考图需由agent实际看图并记录asset-review.json后自动续作；不需要用户确认风格。')
        def asset(aid):
            if aid in self.refs:
                return
            spec = assets[aid]
            for parent in spec.get("references", []):
                asset(parent)
                reviewed(parent)
            if spec.get('local_path') and not self.mock:
                source = Path(spec['local_path'])
                source = source if source.is_absolute() else self.asset_base/source
                raw = self.legacy.normalize_image(source.read_bytes())
                record = {'phase': 'asset', 'status': 'imported_unreviewed', 'sha256': fingerprint(raw), 'actual_reference_count': 0}
            else:
                result = self.image(aid, self.plan["style"]["prompt"]+"\n"+spec.get("prompt", 'MOCK identity reference'), spec.get("ratio", "4:3"), [self.refs[r] for r in spec.get("references", [])], "asset")
                _, raw, cached, record = result
            target = self.root/"assets"/(aid+".png")
            atomic_write(target, raw)
            self.refs[aid] = target
            self.manifest["jobs"][aid] = record
            self.save()
        # Deliberate dependency barrier: reference assets always precede page dispatch.
        for aid in sorted(needed):
            asset(aid)
        if stage == "assets":
            return self.root
        # A reviewed reference cannot be inferred from merely generating a PNG.
        for aid in needed:
            reviewed(aid)
        tasks = []
        bindings = {}
        ratios = self.profile["capabilities"]["ratios"]
        for page in pages:
            if page["route"] in {"native_page", "page_art"}:
                refs = [self.refs[r] for r in reference_ids(self.plan, page)]
                tasks.append((page["id"], page_prompt(self.plan, page), aspect(*page.get("size", [1080,1440]), ratios), refs, "page"))
                bindings[page['id']] = (reference_ids(self.plan, page), identity_bindings(self.plan, page))
            else:
                width, height = page.get("size", [1080,1440])
                for panel in page["panels"]:
                    refs = [self.refs[r] for r in reference_ids(self.plan, page, panel)]
                    tasks.append((panel["id"], page_prompt(self.plan, page, panel), aspect(width*panel["box"][2], height*panel["box"][3], ratios), refs, "panel"))
                    bindings[panel['id']] = (reference_ids(self.plan, page, panel), identity_bindings(self.plan, page, panel))
        with ThreadPoolExecutor(max_workers=self.profile["limits"]["max_inflight"]) as pool:
            remaining = iter(tasks)
            pending = set()
            def fill():
                while not self.errors and len(pending) < self.profile['limits']['max_inflight']:
                    task = next(remaining, None)
                    if task is None:
                        break
                    pending.add(pool.submit(self.image, *task))
            fill()
            while pending:
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    try:
                        uid, raw, path, record = future.result()
                        self.raws[uid] = raw
                        record['reference_ids'], record['identity_bindings'] = bindings[uid]
                        self.manifest['jobs'][uid] = record
                    except Exception as exc:
                        self.errors.append(str(exc) if isinstance(exc, ProductionError) else type(exc).__name__)
                    self.save()
                fill()
        if self.errors:
            self.manifest["status"] = "incomplete"
            self.manifest["errors"] = self.errors
            self.save()
            raise ProductionError("部分任务未完成，成功图已缓存："+"；".join(self.errors))
        letterer = Letterer(self.font)
        page_numbers = {page['id']: i for i, page in enumerate(self.plan['pages'], 1)}
        for page in pages:
            index = page_numbers[page['id']]
            image, checks = letterer.render(page, self.raws, self.plan["keyword"])
            path = self.root/"images"/(f"{index:02d}-"+page["id"]+".png")
            image.save(path)
            self.manifest["pages"][page["id"]] = {"file": path.relative_to(self.root).as_posix(),
                "sha256": fingerprint(path.read_bytes()), "route": page["route"], "lettering_checks": checks,
                "visual_status": "unreviewed", "story_status": "unreviewed", "page_spec_hash": fingerprint(page)}
            self.manifest['pages'][page['id']]['job_ids'] = [p['id'] for p in page['panels']] if page['route'] == 'panels' else [page['id']]
            review_path = self.root/"visual-review.json"
            review = read_json(review_path) if review_path.is_file() else {}
            old = review.get(page["id"], {})
            if old.get("sha256") == self.manifest["pages"][page["id"]]["sha256"]:
                self.manifest["pages"][page["id"]]["visual_status"] = old.get("verdict", "unreviewed")
        write_json(self.root/"storyboard.json", self.plan)
        write_json(self.root/"provider-profile.json", self.profile)
        # No trace archive is built from a directory glob: original text and runtime DB never enter a ZIP.
        contact_sheet([self.root/self.manifest["pages"][p["id"]]["file"] for p in pages], self.root/"contact-sheet.jpg")
        self.manifest["status"] = "mock_layout_only" if self.mock else "awaiting_visual_review"
        self.manifest.pop("errors", None)
        self.save()
        return self.root

    def save(self):
        self.manifest["request_usage"] = self.scheduler.report()
        write_json(self.manifest_path, self.manifest)


def verify_identity_proof(plan, manifest, page):
    """No review flag can turn a zero-reference candidate into a compliant final page."""
    panels = page['panels'] if page['route'] == 'panels' else [None]
    for panel in panels:
        uid = panel['id'] if panel else page['id']
        job = manifest['jobs'].get(uid, {})
        expected = reference_ids(plan, page, panel)
        require(job.get('reference_ids') == expected and job.get('actual_reference_count') == len(expected),
                f'{uid}缺少实际参考图提交记录，不能导出为新版漫画。')
        require(job.get('identity_bindings') == identity_bindings(plan, page, panel), '角色版本与参考图绑定记录不一致。')
        hashes = [manifest['jobs'].get(aid, {}).get('sha256') for aid in expected]
        require(all(hashes) and [r['sha256'] for r in job.get('references', [])] == hashes, '人物参考图已改变或提交摘要不一致，需重新生成受影响画面。')


def export(root, allow_unreviewed=False):
    root = Path(root)
    manifest = read_json(root/"production.json")
    plan = read_json(root/'storyboard.json')
    validate_plan(plan)
    require(manifest.get('identity_contract') == 'required-v1', '旧版无参考试样不能作为当前版本成品，请按人物参考图流程重新制作。')
    review = read_json(root/"visual-review.json") if (root/"visual-review.json").is_file() else {}
    pages = manifest["pages"]
    require(bool(pages), "没有已排版页面。")
    pages = {pid: pages[pid] for pid in manifest.get("planned_page_ids", pages) if pid in pages}
    issues = []
    missing = set(manifest.get("planned_page_ids", pages)) - set(pages)
    issues.extend(sorted(missing))
    for pid, page in pages.items():
        script = next(p for p in plan['pages'] if p['id'] == pid)
        require(page.get('page_spec_hash') == fingerprint(script), '分镜已改变，请重新制作并审阅受影响页面。')
        verify_identity_proof(plan, manifest, script)
        path = root/page["file"]
        require(path.is_file() and fingerprint(path.read_bytes()) == page["sha256"], "图片缺失或摘要改变，请重新审查。")
        check = review.get(pid, {})
        required_checks = {"source_fidelity", "character_continuity", "acting_composition", "exact_text", "reading_order", "mobile_readability"}
        if (check.get("sha256") != page["sha256"] or check.get("verdict") != "accepted" or check.get("blocking_issues")
                or not required_checks <= set(check.get("checks", {}))
                or not all(check["checks"].get(k) is True for k in required_checks)):
            issues.append(pid)
    require(not issues or allow_unreviewed or manifest["mock"], "以下页面尚未完成视觉验收，未标成成品："+", ".join(issues))
    portable = copy.deepcopy(plan)
    used_assets = set(aid for page in plan['pages'] for aid in reference_ids(plan, page))
    all_assets = {a['id']: a for a in plan.get('assets', [])}
    def collect_assets(aid):
        for parent in all_assets[aid].get('references', []):
            if parent not in used_assets:
                used_assets.add(parent);collect_assets(parent)
    for aid in list(used_assets):
        collect_assets(aid)
    portable['assets'] = [a for a in portable.get('assets', []) if a['id'] in used_assets]
    asset_files = {}
    for spec in portable['assets']:
        path = root/'assets'/(spec['id']+'.png')
        require(path.is_file() and fingerprint(path.read_bytes()) == manifest['jobs'][spec['id']]['sha256'], '制作包缺少匹配的人物参考图。')
        spec['local_path'] = 'references/'+spec['id']+'.png'
        asset_files[spec['local_path']] = path
    # Finish all mandatory reference checks before creating either deliverable.
    prefix = "MOCK-" if manifest["mock"] else "REVIEW-" if issues else ""
    stem = "试样" if manifest["mode"] == "style_pilot" else "漫画图集"
    target = root/(prefix+stem+"-images.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for index, (pid, page) in enumerate(pages.items(), 1):
            output.write(root/page["file"], f"{index:02d}-{pid}.png")
    trace = root/(prefix+stem+"-production.zip")
    allowed = ["production.json", "contact-sheet.jpg", "visual-review.json", 'asset-review.json']
    with zipfile.ZipFile(trace, "w", zipfile.ZIP_DEFLATED) as output:
        for name,path in asset_files.items():
            output.write(path,name)
        output.writestr('storyboard.json', json.dumps(portable, ensure_ascii=False, indent=2))
        for name in allowed:
            if (root/name).is_file():
                output.write(root/name, name)
        for job in manifest["jobs"].values():
            if job.get('prompt'):
                output.write(root/job["prompt"], job["prompt"])
    return target, trace
