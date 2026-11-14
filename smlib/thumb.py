"""Thumbnail in the channel style: a graded frame from the clip, a two-line
title (white + yellow), an optional comic 'burst' sticker and the brand name."""
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import captions
from .util import die, run, tool

THUMB_KEYS = {"clip", "t", "title", "zoom", "focus", "sticker", "title_y", "brand", "flip"}


def grab_frame(clip, t):
    info = clip["info"]
    t = max(0.0, min(float(t), info["duration"] - 0.05))
    vf = "scale=2160:-2:flags=lanczos" if info["width"] > 2160 else "null"
    raw = run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", clip["path"],
               "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-c:v", "png", "-"], binary=True)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def crop_to(im, W, H, zoom, focus, cx=0.5):
    """Cover-crop to W:H, then zoom towards focus (fractions of the frame)."""
    ar = W / H
    w, h = im.size
    if w / h > ar:
        nw = round(h * ar)
        x = round((w - nw) * cx)
        im = im.crop((x, 0, x + nw, h))
    else:
        nh = round(w / ar)
        y = (h - nh) // 2
        im = im.crop((0, y, w, y + nh))
    w, h = im.size
    zoom = max(1.0, float(zoom))
    cw, chh = w / zoom, h / zoom
    x = min(max(focus[0] * w - cw / 2, 0), w - cw)
    y = min(max(focus[1] * h - chh / 2, 0), h - chh)
    return im.crop((round(x), round(y), round(x + cw), round(y + chh))).resize((W, H), Image.LANCZOS)


def grade(im, g):
    im = ImageEnhance.Contrast(im).enhance(g["contrast"])
    im = ImageEnhance.Color(im).enhance(g["saturation"])
    im = ImageEnhance.Brightness(im).enhance(g["brightness"])
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    W, H = im.size
    a = np.asarray(im).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    shade = 1.0 - g["vignette"] * np.clip(r - 0.35, 0, 1) ** 1.6 * 2.2
    top = 1.0 - g["top_shade"] * np.clip(1 - yy / (H * 0.36), 0, 1) ** 1.3
    a *= np.clip(shade * top, 0.15, 1.0)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def outlined_text(layer, xy, text, fnt, fill, stroke_w, anchor="mt", shadow=True):
    w, h = layer.size
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((xy[0] + fnt.size * 0.04, xy[1] + fnt.size * 0.07), text, font=fnt,
                                fill=(0, 0, 0, 200), anchor=anchor, stroke_width=stroke_w, stroke_fill=(0, 0, 0, 200))
        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(fnt.size * 0.05)))
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=tuple(fill) + (255,), anchor=anchor,
                               stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255))


def burst(text, style, W, scale=1.0):
    """Comic 'explosion' sticker with red text. -> RGBA image"""
    fs = round(0.062 * W * scale)
    fnt = captions.font(style["fonts"]["sticker"], fs)
    tw = fnt.getlength(text)
    rx, ry = tw / 2 + fs * 1.5, fs * 1.75
    S = 3                                               # supersample for smooth edges
    cw, chh = int((rx * 2 + fs) * S), int((ry * 2 + fs) * S)
    im = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = cw / 2, chh / 2
    spikes = 16
    pts = []
    for i in range(spikes * 2):
        ang = math.pi * i / spikes
        k = 1.0 if i % 2 == 0 else 0.74
        k *= 1.0 + 0.10 * math.sin(i * 2.3)
        pts.append((cx + math.cos(ang) * rx * k * S, cy + math.sin(ang) * ry * k * S))
    d.polygon(pts, fill=(255, 255, 255, 255))
    d.line(pts + [pts[0]], fill=(0, 0, 0, 255), width=max(2, round(fs * 0.10 * S)), joint="curve")
    im = im.resize((cw // S, chh // S), Image.LANCZOS)
    ImageDraw.Draw(im).text((im.width / 2, im.height / 2), text, font=fnt, fill=(222, 24, 32, 255),
                            anchor="mm", stroke_width=max(1, round(fs * 0.045)), stroke_fill=(0, 0, 0, 255))
    return im


def make_thumbnail(plan, out):
    spec = plan["spec"].get("thumbnail")
    if not spec:
        die("short.json has no \"thumbnail\" block, e.g. "
            "{\"clip\": \"a\", \"t\": 12.5, \"title\": [\"MARRY MY\", \"DAUGHTER?\"]}")
    bad = [k for k in spec if k not in THUMB_KEYS]
    if bad:
        die(f"thumbnail: unknown key(s) {bad}. Allowed: {sorted(THUMB_KEYS)}")
    style = plan["style"]
    T = style["thumbnail"]
    W, H = T["size"]
    key = spec.get("clip") or next(iter(plan["clips"]))
    if key not in plan["clips"]:
        die(f"thumbnail.clip '{key}' unknown")
    clip = plan["clips"][key]
    im = grab_frame(clip, spec.get("t", clip["info"]["duration"] / 2))
    im = crop_to(im, W, H, spec.get("zoom", 1.0), spec.get("focus", [0.5, 0.5]), clip["cx"])
    if spec.get("flip"):
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    im = grade(im, T["grade"]).convert("RGBA")

    title = spec.get("title") or []
    if isinstance(title, str):
        title = [title]
    if title:
        fs = round(T["title_size"] * W)
        while fs > 30:
            fnt = captions.font(style["fonts"]["title"], fs)
            if max(fnt.getlength(t) for t in title) + fs * 0.2 <= T["title_max_w"] * W:
                break
            fs -= 3
        y = spec.get("title_y", T["title_y"]) * H
        for i, line in enumerate(title):
            col = T["title_colors"][min(i, len(T["title_colors"]) - 1)]
            outlined_text(im, (W / 2, y), line, fnt, col, max(2, round(fs * 0.075)))
            y += fs * 1.16

    st = spec.get("sticker")
    if st:
        st = {"text": st} if isinstance(st, str) else st
        b = burst(st["text"], style, W, st.get("size", 1.0))
        b = b.rotate(st.get("rot", -5), expand=True, resample=Image.BICUBIC)
        px, py = st.get("at", [0.70, 0.55])
        x = min(max(round(px * W - b.width / 2), 0), W - b.width)
        yy = min(max(round(py * H - b.height / 2), 0), H - b.height)
        im.alpha_composite(b, (x, yy))

    if spec.get("brand", True) and style.get("brand"):
        fnt = captions.font(style["fonts"]["caption"], round(0.026 * W))
        text = "  ".join(style["brand"].upper()) if False else "  ".join(style["brand"].upper())
        outlined_text(im, (W / 2, T["brand_y"] * H), text, fnt, (255, 255, 255), 0, anchor="mm")
    im.convert("RGB").save(out, quality=93)
    return out
