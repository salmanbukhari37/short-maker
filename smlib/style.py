"""House style. DEFAULTS are overridden by style.json (channel-wide) and then by
an optional "style" block inside a short's short.json (one-off tweaks)."""
from pathlib import Path

from .util import ROOT, deep_merge, load_json

DEFAULTS = {
    "brand": "FROVIXA",
    "fonts": {
        "caption": "fonts/Montserrat-Bold.ttf",
        "title": "fonts/Montserrat-ExtraBoldItalic.ttf",
        "sticker": "fonts/Montserrat-BlackItalic.ttf",
        "emoji": "fonts/NotoColorEmoji.ttf",
    },
    # All caption sizes are fractions: of frame WIDTH for size/max_w, of frame HEIGHT for y,
    # of the font size for pad/radius/stroke.
    "caption": {
        "size": 0.055, "y": 0.195, "max_w": 0.76,
        "pad_x": 0.55, "pad_y": 0.32, "radius": 0.36, "line_height": 1.16,
        "stroke": 0.045, "shadow": 0.5,
        "pop": True,            # small slide-in when a caption appears
        "lead": 0.04,           # show caption this many seconds before its words
        "hold": 0.35,           # keep last caption of a line this long after the voice ends
        "max_words": 6,         # auto-split longer lines into chunks
        "positions": {"top": 0.195, "mid": 0.50, "low": 0.70},
    },
    # Caption pill colour per speaker [r, g, b, alpha 0-255]. Unknown speakers use "default".
    "speakers": {
        "trevor":   {"pill": [233, 190, 22, 205]},
        "michael":  {"pill": [58, 58, 58, 170]},
        "franklin": {"pill": [34, 139, 84, 205]},
        "npc":      {"pill": [37, 99, 176, 200]},
        "cop":      {"pill": [29, 78, 216, 205]},
        "hook":     {"pill": [233, 190, 22, 205]},
        "default":  {"pill": [58, 58, 58, 170]},
    },
    "text_color": [255, 255, 255],
    "stroke_color": [28, 28, 28],
    # voice file name prefix (lowercase) -> speaker key
    "aliases": {"black-american-npc": "npc", "mind-cop": "cop", "carl-the-npc": "carl"},
    "audio": {
        "voice_db": -19.0,      # RMS level every voice line is normalised to
        "bed_db": 0.0,          # gain on the clip's own (game) audio
        "duck_db": -10.0,       # how far game audio/music drops under a voice
        "line_gap": 0.30,       # default pause between consecutive lines without "at"
        "music_db": -20.0,
        "sfx_db": -6.0,
        "master_lufs": -14.0,
    },
    "video": {
        "res": "8k",            # 1080 | 1440 | 4k | 8k
        "fps": "source",        # "source" (max 60) or a number
        "codec": "auto",        # auto = NVIDIA GPU (hevc_nvenc) when present, else x264
        "crf": {"1080": 16, "1440": 16, "4k": 15, "8k": 19},   # x264 quality (lower = bigger/better)
        "x264_preset": "veryfast", "nvenc_cq": 18,
        "grade": None,          # optional whole-video look: punch | warm | None
        "chunk_s": {"1080": 20, "1440": 10, "4k": 5, "8k": 2},
    },
    "cta": {                    # animated like+subscribe overlay (file relative to shorts-maker)
        "file": "../files/Frovixa_LikeSubscribe_TRANSPARENT.mov",
        "audio_db": -10.0,
    },
    "thumbnail": {
        "size": [1080, 1920],
        "title_colors": [[255, 255, 255], [255, 208, 0]],
        "title_y": 0.085, "title_max_w": 0.92, "title_size": 0.125,
        "grade": {"contrast": 1.12, "saturation": 1.22, "brightness": 1.0, "vignette": 0.42, "top_shade": 0.40},
        "brand_y": 0.955,
    },
}

RES = {"1080": (1080, 1920), "1440": (1440, 2560), "4k": (2160, 3840), "8k": (4320, 7680),
       "preview": (540, 960)}


def load_style(extra=None):
    st = DEFAULTS
    p = ROOT / "style.json"
    if p.exists():
        st = deep_merge(st, load_json(p))
    if extra:
        st = deep_merge(st, extra)
    return st


def asset(rel):
    """Resolve a style path (relative to the shorts-maker folder)."""
    p = Path(rel)
    return p if p.is_absolute() else (ROOT / p).resolve()
