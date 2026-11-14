"""Caption text handling and pill rendering (Pillow). No ffmpeg text filters are
used anywhere, so there are no font-path / escaping problems on Windows."""
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .style import asset

_EMO = "\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿⌀-⏿⤀-⥿〰〽㊗㊙"
EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}|[" + _EMO + "]"
    "(?:️|⃣|[\U0001F3FB-\U0001F3FF]|‍[" + _EMO + "]️?)*)")
_PUNCT_END = re.compile(r"[,.!?;:…]+[\"')\]]*$")


# ----------------------------------------------------------------- text logic

def strip_emoji(s):
    return EMOJI_RE.sub("", s).replace("️", "")


def word_count(s):
    return len([w for w in strip_emoji(s.replace("/", " ")).split() if re.search(r"\w", w)])


def split_chunks(text, max_words):
    """'a | b' -> explicit chunks. Otherwise long lines are split at punctuation
    so each caption stays short. A chunk may contain '/' forced line breaks."""
    text = text.strip()
    if "|" in text:
        return [c.strip() for c in text.split("|") if c.strip()]
    if "/" in text or word_count(text) <= max_words:
        return [text]
    words = text.split()
    pieces, cur = [], []
    for w in words:
        cur.append(w)
        if _PUNCT_END.search(strip_emoji(w)) and word_count(" ".join(cur)) >= 1:
            pieces.append(cur)
            cur = []
    if cur:
        if pieces and word_count(" ".join(cur)) == 0:
            pieces[-1] += cur            # trailing emoji stays with its sentence
        else:
            pieces.append(cur)
    merged = []
    for p in pieces:                      # merge neighbours while they stay short
        if merged and word_count(" ".join(merged[-1] + p)) <= max_words:
            merged[-1] = merged[-1] + p
        else:
            merged.append(list(p))
    out = []
    for p in merged:                      # split anything still too long evenly
        n = word_count(" ".join(p))
        if n <= max_words:
            out.append(" ".join(p))
            continue
        parts = math.ceil(n / max_words)
        size = math.ceil(len(p) / parts)
        for i in range(0, len(p), size):
            out.append(" ".join(p[i:i + size]))
    return out


def chunk_weight(chunk):
    """Rough speaking length of a chunk (letters + pauses)."""
    s = strip_emoji(chunk.replace("/", " "))
    return max(1.0, len(re.findall(r"\w", s)) + 2.0 * len(re.findall(r"…|\.\.\.|[,.!?]", s)))


def tokenize(line):
    """-> [('t', text) | ('e', emoji)]"""
    out, pos = [], 0
    for m in EMOJI_RE.finditer(line):
        if m.start() > pos:
            out.append(("t", line[pos:m.start()]))
        out.append(("e", m.group(0)))
        pos = m.end()
    if pos < len(line):
        out.append(("t", line[pos:]))
    return [(k, s.replace("️", "") if k == "t" else s) for k, s in out if s]


# ------------------------------------------------------------------ rendering

@lru_cache(maxsize=64)
def font(path, size):
    return ImageFont.truetype(str(asset(path)), int(size))


@lru_cache(maxsize=256)
def emoji_img(ch, height, emoji_font):
    """Colour emoji as an RGBA image `height` px tall, or None if the font lacks it."""
    try:
        f = font(emoji_font, 109)       # NotoColorEmoji is a bitmap font: only size 109 exists
    except OSError:
        return None
    im = Image.new("RGBA", (int(109 * 1.6 * max(1, len(ch))), 150), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((8, 8), ch, font=f, embedded_color=True)
    box = im.getbbox()
    if not box:
        return None
    im = im.crop(box)
    h = max(2, int(height))
    w = max(2, round(im.width * h / im.height))
    return im.resize((w, h), Image.LANCZOS)


class Layout:
    """Measures and wraps caption text for one font size."""

    def __init__(self, style, W, size_frac=None):
        c = style["caption"]
        self.style, self.W = style, W
        self.fs = max(8, round((size_frac or c["size"]) * W))
        self.font = font(style["fonts"]["caption"], self.fs)
        self.esize = round(self.fs * 0.98)
        self.egap = round(self.fs * 0.06)
        self.maxw = c["max_w"] * W

    def runs(self, line):
        out = []
        for kind, s in tokenize(line):
            if kind == "e":
                img = emoji_img(s, self.esize, self.style["fonts"]["emoji"])
                if img is not None:
                    out.append(("e", img, img.width + 2 * self.egap))
                    continue
                s = ""                   # emoji missing from font: drop it
            if s:
                out.append(("t", s, self.font.getlength(s)))
        return out

    def width(self, line):
        return sum(r[2] for r in self.runs(line.strip()))

    def wrap(self, chunk):
        """chunk text -> list of lines. '/' forces breaks; otherwise balanced wrap."""
        lines = []
        for part in chunk.split("/"):
            part = " ".join(part.split())
            if not part:
                continue
            if self.width(part) <= self.maxw:
                lines.append(part)
                continue
            words = part.split(" ")
            best = None
            for i in range(1, len(words)):        # best 2-line split
                a, b = " ".join(words[:i]), " ".join(words[i:])
                m = max(self.width(a), self.width(b))
                if best is None or m < best[0]:
                    best = (m, [a, b])
            if best and best[0] <= self.maxw:
                lines += best[1]
                continue
            cur = ""                               # greedy fallback
            for w in words:
                t = (cur + " " + w).strip()
                if cur and self.width(t) > self.maxw:
                    lines.append(cur)
                    cur = w
                else:
                    cur = t
            if cur:
                lines.append(cur)
        return lines or [""]


def render_caption(chunk, who, style, W):
    """-> (RGBA image, list of wrapped lines). Shrinks the font if a word is too wide."""
    c = style["caption"]
    frac = c["size"]
    for _ in range(6):
        lay = Layout(style, W, frac)
        lines = lay.wrap(chunk)
        widest = max(lay.width(ln) for ln in lines)
        if widest <= lay.maxw * 1.02 and len(lines) <= 3:
            break
        frac *= 0.9
    fs = lay.fs
    spk = style["speakers"].get(who) or style["speakers"]["default"]
    pill = tuple(spk.get("pill", style["speakers"]["default"]["pill"]))
    tcol = tuple(spk.get("text", style["text_color"])) + (255,)
    scol = tuple(style["stroke_color"]) + (255,)
    sw = max(1, round(c["stroke"] * fs))
    lh = round(c["line_height"] * fs)
    padx, pady = round(c["pad_x"] * fs), round(c["pad_y"] * fs)
    m = round(0.2 * fs)                               # margin so the shadow is not clipped
    asc, desc = lay.font.getmetrics()
    cap_h = -lay.font.getbbox("H", anchor="ls")[1]
    bw = math.ceil(widest)
    w = bw + 2 * padx + 2 * m
    h = len(lines) * lh + 2 * pady + 2 * m
    w += w % 2
    h += h % 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((m, m, w - m - 1, h - m - 1),
                                          radius=round(c["radius"] * fs), fill=pill)
    text = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    emojis = []
    for i, ln in enumerate(lines):
        runs = lay.runs(ln)
        x = (w - sum(r[2] for r in runs)) / 2.0
        base = m + pady + i * lh + (lh - (asc + desc)) / 2.0 + asc
        for kind, obj, rw in runs:
            if kind == "t":
                td.text((x, base), obj, font=lay.font, fill=tcol, anchor="ls",
                        stroke_width=sw, stroke_fill=scol)
            else:
                emojis.append((obj, round(x + lay.egap), round(base - cap_h / 2.0 - obj.height / 2.0)))
            x += rw
    if c.get("shadow", 0) > 0:
        a = text.getchannel("A").filter(ImageFilter.GaussianBlur(max(1.0, 0.07 * fs)))
        a = a.point(lambda v: int(v * c["shadow"]))
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sh.putalpha(a)
        off = min(h - 1, round(0.05 * fs))
        img.alpha_composite(sh.crop((0, 0, w, h - off)), (0, off))
    img.alpha_composite(text)
    for e, ex, ey in emojis:
        img.alpha_composite(e, (max(0, ex), max(0, ey)))
    return img, lines


def caption_y(pos, style):
    """'top' | 'mid' | 'low' | number (fraction of height) -> fraction"""
    c = style["caption"]
    if pos is None:
        return c["y"]
    if isinstance(pos, (int, float)):
        return float(pos)
    if pos in c["positions"]:
        return c["positions"][pos]
    raise ValueError(f"unknown caption pos '{pos}' (use {', '.join(c['positions'])} or a number 0-1)")
