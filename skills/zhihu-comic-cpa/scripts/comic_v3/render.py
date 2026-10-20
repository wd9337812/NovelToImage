"""Editable scene-integrated lettering; no destructive crop or caption bands."""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .core import ProductionError, require, overlap


def pixels(box, width, height):
    x, y, w, h = box
    return [round(x*width), round(y*height), round((x+w)*width), round((y+h)*height)]


def lines_for(text, font, width):
    lines = []
    for paragraph in text.split("\n"):
        group = []
        line = ""
        for char in paragraph:
            if line and font.getlength(line+char) > width:
                group.append(line)
                line = char
            else:
                line += char
        group.append(line)
        if len(group) >= 2 and len(group[-1]) <= 2 and len(group[-2]) > 4:
            combined = group[-2]+group[-1]
            split = math.ceil(len(combined)/2)
            if combined[split:split+1] in "，。！？、；：）》」』】":
                split -= 1
            a, b = combined[:split], combined[split:]
            if font.getlength(a) <= width and font.getlength(b) <= width:
                group[-2:] = [a,b]
        lines.extend(group)
    return lines


class Letterer:
    def __init__(self, font, ink="#262327", paper="#ffffff"):
        self.font, self.ink, self.paper = str(font), ink, paper
        self.checks = []

    def label(self, canvas, item, bounds, point=42):
        draw = ImageDraw.Draw(canvas)
        x, y, r, b = bounds
        pad = max(13, round(canvas.width*.012))
        kind = item["type"]
        bubble = kind in {"dialogue", "thought"}
        # A centered rectangle occupying <=70% of both ellipse axes stays inside
        # the curve. Checking only the ellipse's bounding rectangle clips glyphs.
        padx = max(pad, math.ceil((r-x)*.15)) if bubble else pad
        pady = max(pad, math.ceil((b-y)*.15)) if bubble else pad
        chosen = None
        for size in range(point, 35, -1):
            font = ImageFont.truetype(self.font, size)
            lines = lines_for(item["text"], font, r-x-2*padx)
            line_height = math.ceil(size*1.38)
            if len(lines)*line_height <= b-y-2*pady:
                chosen = font, lines, line_height, size
                break
        require(chosen is not None, "气泡文字在手机可读字号下装不下，请扩大气泡／拆句；没有缩成小字。")
        font, lines, line_height, size = chosen
        if kind in {"dialogue", "thought"}:
            draw.ellipse(bounds, fill="white", outline=self.ink, width=3)
            if "tail_pixels" in item:
                tx, ty = item["tail_pixels"]
                cx, cy = (x+r)/2, (y+b)/2
                dx, dy = tx-cx, ty-cy
                length = max(1, math.hypot(dx,dy))
                factor = 1 / max(1e-6, math.sqrt((dx/((r-x)/2))**2+(dy/((b-y)/2))**2))
                sx, sy = cx+dx*factor, cy+dy*factor
                # Point toward the speaker without drawing a spear across their face.
                remaining = math.hypot(tx-sx, ty-sy)
                if remaining > canvas.width*.10:
                    scale = canvas.width*.10/remaining
                    tx, ty = sx+(tx-sx)*scale, sy+(ty-sy)*scale
                px, py = -dy/length*11, dx/length*11
                triangle = [(sx+px,sy+py),(tx,ty),(sx-px,sy-py)]
                if kind == "dialogue":
                    draw.polygon(triangle, fill="white")
                    draw.line(triangle, fill=self.ink, width=3)
                else:
                    for t, radius in ((.6, 7), (.85, 4)):
                        px, py = cx+(tx-cx)*t, cy+(ty-cy)*t
                        draw.ellipse((px-radius, py-radius, px+radius, py+radius), fill="white", outline=self.ink, width=2)
        elif kind in {"narration", "keyword"}:
            draw.rounded_rectangle(bounds, radius=12, fill="#fffef8", outline=self.ink, width=2)
        center = kind in {"dialogue", "thought", "keyword"}
        top = y + ((b-y)-len(lines)*line_height)/2
        for line in lines:
            left = (x+r-font.getlength(line))/2 if center else x+pad
            draw.text((left, top), line, font=font, fill=self.ink, anchor="lt")
            top += line_height
        self.checks.append({"text": item["text"], "font_size": size, "lines": len(lines), "bounds": bounds, "fits": True})

    def place_art(self, canvas, raw, box):
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            w, h = box[2]-box[0], box[3]-box[1]
            # Contain never removes a face/prop. Incompatible planned ratios fail visibly.
            ratio_error = abs((image.width/image.height)/(w/h)-1)
            require(ratio_error < .13, "返回画幅与分格不匹配，请核对尺寸映射；未强行裁切。")
            fit = ImageOps.contain(image, (w, h), method=Image.Resampling.LANCZOS)
            canvas.paste(fit, (box[0]+(w-fit.width)//2, box[1]+(h-fit.height)//2))

    def render(self, page, raws, keyword=""):
        width, height = page.get("size", [1080, 1440])
        canvas = Image.new("RGB", (width, height), self.paper)
        route = page["route"]
        self.checks = []
        if route in {"native_page", "page_art"}:
            self.place_art(canvas, raws[page["id"]], (0, 0, width, height))
            if route == "native_page":
                return canvas, []
        for panel in page["panels"]:
            outer = pixels(panel["box"], width, height)
            pw, ph = outer[2]-outer[0], outer[3]-outer[1]
            if route == "panels":
                self.place_art(canvas, raws[panel["id"]], outer)
                ImageDraw.Draw(canvas).rectangle(outer, outline=self.ink, width=3)
            for item in panel.get("texts", []):
                rect = pixels(item["box"], pw, ph)
                rect = [rect[0]+outer[0], rect[1]+outer[1], rect[2]+outer[0], rect[3]+outer[1]]
                text = dict(item)
                if "tail" in text:
                    text["tail_pixels"] = [outer[0]+round(text["tail"][0]*pw), outer[1]+round(text["tail"][1]*ph)]
                self.label(canvas, text, rect, page.get("font_size", 42))
        if keyword:
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(self.font, 18)
            for label, right in ((keyword+" · "+str(page.get("label",page["id"])),False),("AI辅助创作",True)):
                tw = round(font.getlength(label))
                left = width-tw-17 if right else 8
                draw.rounded_rectangle((left-5,height-28,left+tw+5,height-3),radius=4,fill="white")
                draw.text((left,height-26),label,font=font,fill=self.ink,anchor="lt")
        return canvas, list(self.checks)


def contact_sheet(paths, output, columns=2):
    thumb_width = 480
    with Image.open(paths[0]) as image:
        thumb_height = round(thumb_width*image.height/image.width)
    sheet = Image.new("RGB", (thumb_width*columns, thumb_height*math.ceil(len(paths)/columns)), "#ecebea")
    for i, path in enumerate(paths):
        with Image.open(path) as image:
            sheet.paste(ImageOps.contain(image.convert("RGB"), (thumb_width, thumb_height)),
                        (i % columns*thumb_width, i//columns*thumb_height))
    sheet.save(output, quality=94)
