from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import io
import json
from pathlib import Path
import zipfile

from PIL import Image

from . import VERSION
from .core import ProductionError, require, fingerprint, read_json, write_json, atomic_write, validate_plan
from .provider import ImageProvider, validate_profile
from .render import Letterer, contact_sheet
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
    chunks.append("If identity reference images are supplied, preserve that exact cast identity, hair and wardrobe; do not copy the reference-sheet grid or poses into the story.")
    return "\n\n".join(chunks)


class Production:
    def __init__(self, plan, profile, story, root, legacy, budget=12, mock=False, transport=None):
        self.plan = validate_plan(copy.deepcopy(plan), story)
        self.profile = validate_profile(profile)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.legacy, self.mock = legacy, mock
        state_file = profile.get("runtime", {}).get("state_file", str(Path.cwd()/"runs/.cache/v3-scheduler.sqlite3"))
        self.scheduler = Scheduler(state_file, profile, fingerprint(str(self.root.resolve()))[:20], budget)
        self.provider = ImageProvider(profile, self.scheduler, legacy, transport=transport)
        self.manifest_path = self.root/"production.json"
        self.manifest = read_json(self.manifest_path) if self.manifest_path.is_file() else {"version": VERSION, "jobs": {}, "pages": {}}
        self.manifest.update(keyword=plan["keyword"], mode=plan["mode"], mock=mock, status="in_progress")
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
        needed = set(r for p in pages for r in p.get("references", []))
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
        def asset(aid):
            if aid in self.refs:
                return
            spec = assets[aid]
            for parent in spec.get("references", []):
                asset(parent)
            result = self.image(aid, self.plan["style"]["prompt"]+"\n"+spec["prompt"], spec.get("ratio", "4:3"), [self.refs[r] for r in spec.get("references", [])], "asset")
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
        if needed and not self.mock:
            review_file = self.root/"asset-review.json"
            review = read_json(review_file) if review_file.is_file() else {}
            for aid in needed:
                accepted = review.get(aid, {})
                require(accepted.get("accepted") is True and accepted.get("sha256") == fingerprint(self.refs[aid].read_bytes()), "角色／风格参考尚未实际看图确认，请审阅资产后记录asset-review.json。")
        tasks = []
        ratios = self.profile["capabilities"]["ratios"]
        for page in pages:
            refs = [self.refs[r] for r in page.get("references", [])]
            if page["route"] in {"native_page", "page_art"}:
                tasks.append((page["id"], page_prompt(self.plan, page), aspect(*page.get("size", [1080,1440]), ratios), refs, "page"))
            else:
                width, height = page.get("size", [1080,1440])
                for panel in page["panels"]:
                    tasks.append((panel["id"], page_prompt(self.plan, page, panel), aspect(width*panel["box"][2], height*panel["box"][3], ratios), refs, "panel"))
        with ThreadPoolExecutor(max_workers=self.profile["limits"]["max_inflight"]) as pool:
            futures = [pool.submit(self.image, *task) for task in tasks]
            for future in as_completed(futures):
                try:
                    uid, raw, path, record = future.result()
                    self.raws[uid] = raw
                    self.manifest["jobs"][uid] = record
                except Exception as exc:
                    self.errors.append(str(exc) if isinstance(exc, ProductionError) else type(exc).__name__)
                self.save()
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


def export(root, allow_unreviewed=False):
    root = Path(root)
    manifest = read_json(root/"production.json")
    review = read_json(root/"visual-review.json") if (root/"visual-review.json").is_file() else {}
    pages = manifest["pages"]
    require(bool(pages), "没有已排版页面。")
    pages = {pid: pages[pid] for pid in manifest.get("planned_page_ids", pages) if pid in pages}
    issues = []
    missing = set(manifest.get("planned_page_ids", pages)) - set(pages)
    issues.extend(sorted(missing))
    for pid, page in pages.items():
        path = root/page["file"]
        require(path.is_file() and fingerprint(path.read_bytes()) == page["sha256"], "图片缺失或摘要改变，请重新审查。")
        check = review.get(pid, {})
        required_checks = {"source_fidelity", "character_continuity", "acting_composition", "exact_text", "reading_order", "mobile_readability"}
        if (check.get("sha256") != page["sha256"] or check.get("verdict") != "accepted" or check.get("blocking_issues")
                or not required_checks <= set(check.get("checks", {}))
                or not all(check["checks"].get(k) is True for k in required_checks)):
            issues.append(pid)
    require(not issues or allow_unreviewed or manifest["mock"], "以下页面尚未完成视觉验收，未标成成品："+", ".join(issues))
    prefix = "MOCK-" if manifest["mock"] else "REVIEW-" if issues else ""
    stem = "试样" if manifest["mode"] == "style_pilot" else "漫画图集"
    target = root/(prefix+stem+"-images.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for index, (pid, page) in enumerate(pages.items(), 1):
            output.write(root/page["file"], f"{index:02d}-{pid}.png")
    trace = root/(prefix+stem+"-production.zip")
    allowed = ["storyboard.json", "production.json", "contact-sheet.jpg", "visual-review.json"]
    with zipfile.ZipFile(trace, "w", zipfile.ZIP_DEFLATED) as output:
        for name in allowed:
            if (root/name).is_file():
                output.write(root/name, name)
        for job in manifest["jobs"].values():
            output.write(root/job["prompt"], job["prompt"])
    return target, trace
