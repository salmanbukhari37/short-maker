"""Folder discovery + short.json -> a fully resolved plan (all times in seconds)."""
import re
from pathlib import Path

from . import audio, captions, video
from .style import asset, load_style
from .util import AUDIO_EXT, VIDEO_EXT, SMError, die, load_json, probe, ts

VOICE_DIRS = ["", "audio", "voice", "voices", "vo"]
SFX_DIRS = ["sound_effect", "sound_effects", "sfx", "music"]
TOP_KEYS = {"name", "clips", "timeline", "hook", "lines", "captions", "sfx", "fx", "music",
            "cta", "thumbnail", "style", "fps"}
SEG_KEYS = {"clip", "in", "out", "speed", "zoom", "focus", "look", "gain", "mute", "hold"}
LINE_KEYS = {"who", "audio", "text", "at", "gap", "gain", "hold", "pos", "dur", "cuts"}
CAP_KEYS = {"text", "who", "at", "end", "dur", "pos"}
LOOKS = {"drama", "punch", "warm", "bw", "dark"}
SFX_NAMES = set(audio.SYNTH)
_NAME_RE = re.compile(r"^(?P<spk>.+?)-(?P<date>\d{4}-\d{2}-\d{2}-\d{2}-\d{2})-(?P<rest>.*)$")


# ------------------------------------------------------------------ discovery

def parse_voice_name(stem, style):
    """'Trevor-Philips-2026-11-13-18-45-[proud]-I-make-thi' -> (who, tags, hint, date)"""
    m = _NAME_RE.match(stem)
    if not m:
        return None, "", stem.replace("-", " ").replace("_", " ").strip(), ""
    spk = re.sub(r"\(?gta-?v\)?", "", m.group("spk").lower()).strip("-_ ")
    spk = re.sub(r"-+", "-", spk)
    who = style["aliases"].get(spk) or spk.split("-")[0]
    rest = m.group("rest")
    tags = ", ".join(t.strip("-, ").replace("-", " ") for t in re.findall(r"[\[(]([^\])]*)[\])]", rest))
    hint = re.sub(r"[\[(][^\])]*[\])]", " ", rest).replace("-", " ")
    hint = re.sub(r"\s+", " ", hint).strip(" “”\"'")
    return who, tags, hint, m.group("date")


def is_output(p):
    return bool(re.search(r"_(FINAL_[0-9A-Za-z]+|PREVIEW)$", p.stem))


def discover(folder, style):
    folder = Path(folder)
    if not folder.is_dir():
        die(f"folder not found: {folder}")
    vids = [p for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if p.suffix.lower() in VIDEO_EXT and p.stat().st_size > 10000 and not is_output(p)]
    videos = [{"key": chr(ord("a") + i), "path": p} for i, p in enumerate(vids[:26])]
    voices, sfx = [], []
    for d in VOICE_DIRS:
        dd = folder / d if d else folder
        if dd.is_dir():
            for p in sorted(dd.iterdir()):
                if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                    who, tags, hint, date = parse_voice_name(p.stem, style)
                    voices.append({"path": p, "who": who, "tags": tags, "hint": hint, "date": date})
    voices.sort(key=lambda v: (v["date"], v["path"].name.lower()))
    for i, v in enumerate(voices):
        v["idx"] = i + 1
    for d in SFX_DIRS:
        dd = folder / d
        if dd.is_dir():
            sfx += [{"path": p} for p in sorted(dd.iterdir())
                    if p.is_file() and p.suffix.lower() in AUDIO_EXT]
    return {"videos": videos, "voices": voices, "sfx": sfx}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def find_audio(ref, found, folder, what="audio"):
    """ref: voice number from scan, a unique part of the file name, or a path."""
    if isinstance(ref, bool):
        die(f"{what}: bad reference {ref!r}")
    if isinstance(ref, int):
        for v in found["voices"]:
            if v["idx"] == ref:
                return v
        die(f"{what}: no voice #{ref} (scan lists {len(found['voices'])} voice files)")
    p = Path(folder) / str(ref)
    if p.is_file():
        for v in found["voices"]:
            if v["path"] == p:
                return v
        return {"path": p, "who": None, "hint": p.stem, "tags": "", "date": ""}
    key = _norm(ref)
    pool = found["voices"] + found["sfx"]
    hits = [v for v in pool if key and key in _norm(v["path"].stem)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        names = "\n    ".join(f"#{v.get('idx', '-')} {v['path'].name}" for v in pool) or "(none)"
        die(f"{what}: nothing matches {ref!r}. Available:\n    {names}")
    if len({(v.get("who"), _norm(v.get("hint", ""))) for v in hits}) == 1:
        return hits[-1]                  # same line recorded twice: newest take wins
    names = "\n    ".join(f"#{v.get('idx', '-')} {v['path'].name}" for v in hits)
    die(f"{what}: {ref!r} matches several files, use the #number instead:\n    {names}")


# ------------------------------------------------------------------- resolve

def _keys(d, allowed, what):
    bad = [k for k in d if k not in allowed and not k.startswith("_")]
    if bad:
        die(f"{what}: unknown key(s) {bad}. Allowed: {sorted(allowed)}")


def _num(v, what, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        die(f"{what} must be a number, got {v!r}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        die(f"{what}={v} is out of range ({lo}..{hi})")
    return float(v)


def load_spec(folder):
    p = Path(folder) / "short.json"
    if not p.exists():
        die(f"no short.json in {folder} - run 'scan' first (it writes a draft)")
    spec = load_json(p)
    if not isinstance(spec, dict):
        die("short.json must be a JSON object")
    _keys(spec, TOP_KEYS, "short.json")
    return spec


def resolve(folder):
    folder = Path(folder).resolve()
    spec = load_spec(folder)
    style = load_style(spec.get("style"))
    found = discover(folder, style)
    warn = []

    # ---- clips
    clips = {}
    raw_clips = spec.get("clips") or {v["key"]: v["path"].name for v in found["videos"][:1]}
    if not raw_clips:
        die("no video file in the folder and no \"clips\" in short.json")
    for key, val in raw_clips.items():
        c = {"file": val} if isinstance(val, str) else dict(val)
        _keys(c, {"file", "fit", "cx", "bars"}, f"clips.{key}")
        path = (folder / c["file"]).resolve()
        if not path.is_file():
            die(f"clips.{key}: file not found: {c['file']}")
        info = probe(path)
        if not info["has_video"]:
            die(f"clips.{key}: {path.name} has no video stream")
        fit = c.get("fit", "crop")
        if fit not in ("crop", "blur"):
            die(f"clips.{key}.fit must be 'crop' or 'blur'")
        if c.get("bars", "auto") not in ("auto", "keep"):
            die(f"clips.{key}.bars must be 'auto' (cut black bars away) or 'keep'")
        box = video.detect_bars(path, info, folder / "_sm") if c.get("bars", "auto") == "auto" else None
        clips[key] = {"key": key, "path": path, "info": info, "fit": fit, "box": box,
                      "cx": _num(c.get("cx", 0.5), f"clips.{key}.cx", 0, 1)}
    first = next(iter(clips))

    # ---- frame rate and time grid
    fps = spec.get("fps", style["video"]["fps"])
    if fps == "source":
        fps = min(60, round(clips[first]["info"]["fps"]) or 30)
    fps = int(_num(fps, "fps", 12, 120))
    pfps = fps // 2 if fps >= 48 and fps % 2 == 0 else fps      # preview frame rate

    def q(t):                                                     # snap to the preview frame grid
        return round(t * pfps) / pfps

    # ---- timeline
    segs, t = [], 0.0
    for i, item in enumerate(spec.get("timeline") or [{}]):
        what = f"timeline[{i}]"
        if isinstance(item, list):
            if len(item) < 3:
                die(f"{what}: list form is [clip, in, out, {{options}}]")
            s = dict(item[3]) if len(item) > 3 else {}
            s.update(clip=item[0], **{"in": item[1], "out": item[2]})
        else:
            s = dict(item)
        _keys(s, SEG_KEYS, what)
        key = s.get("clip", first)
        if key not in clips:
            die(f"{what}: unknown clip '{key}' (have: {', '.join(clips)})")
        dur = clips[key]["info"]["duration"]
        a = _num(s.get("in", 0), f"{what}.in", 0)
        b = _num(s.get("out", dur), f"{what}.out", 0)
        if b > dur + 0.05:
            warn.append(f"{what}: out={b} is past the end of clip {key} ({dur:.2f}s) - clamped")
        b = min(b, dur)
        if b - a < 0.05:
            die(f"{what}: in={a} out={b} is empty (clip {key} is {dur:.2f}s long)")
        speed = _num(s.get("speed", 1), f"{what}.speed", 0.1, 8)
        z = s.get("zoom", 1)
        z0, z1 = (z if isinstance(z, list) else [z, z])
        z0, z1 = _num(z0, f"{what}.zoom", 1, 4), _num(z1, f"{what}.zoom", 1, 4)
        fx, fy = s.get("focus", [0.5, 0.5])
        look = s.get("look")
        if look and look not in LOOKS:
            die(f"{what}.look '{look}' unknown. Use one of: {sorted(LOOKS)}")
        content = max(1.0 / pfps, q((b - a) / speed))
        hold = q(_num(s.get("hold", 0), f"{what}.hold", 0, 30))
        segs.append({"clip": key, "in": a, "out": b, "speed": speed, "z0": z0, "z1": z1,
                     "fx": _num(fx, f"{what}.focus", 0, 1), "fy": _num(fy, f"{what}.focus", 0, 1),
                     "look": look, "gain": _num(s.get("gain", 0), f"{what}.gain", -60, 24),
                     "mute": bool(s.get("mute", False)), "content": content, "hold": hold,
                     "t0": t, "t1": t + content + hold, "shakes": []})
        t = segs[-1]["t1"]
    T = t
    A = style["audio"]
    C = style["caption"]

    # ---- voice lines (+ their captions)
    voices, caps, prev_end = [], [], None
    for i, ln in enumerate(spec.get("lines") or []):
        what = f"lines[{i}]"
        if not isinstance(ln, dict):
            die(f"{what} must be an object")
        _keys(ln, LINE_KEYS, what)
        v = an = None
        if "audio" in ln:
            v = find_audio(ln["audio"], found, folder, what)
            an = audio.analyze_voice(v["path"])
            dur = an["dur"]
        else:
            dur = _num(ln.get("dur", 1.5), f"{what}.dur", 0.1, 60)
        if "at" in ln:
            at = _num(ln["at"], f"{what}.at", 0)
        elif prev_end is None:
            die(f"{what}: the first line needs \"at\" (seconds on the final timeline)")
        else:
            at = prev_end + _num(ln.get("gap", A["line_gap"]), f"{what}.gap", -5, 60)
        end = at + dur
        who = ln.get("who") or (v and v.get("who")) or "default"
        if prev_end is not None and at < prev_end - 0.05:
            warn.append(f"{what} starts at {ts(at)} while the previous line is still speaking (until {ts(prev_end)})")
        if end > T + 0.05:
            warn.append(f"{what} ends at {ts(end)} but the video is only {ts(T)} long")
        if v:
            voices.append({"path": v["path"], "at": at, "dur": dur, "who": who, "i": i,
                           "gain": _num(ln.get("gain", 0), f"{what}.gain", -40, 24)})
        text = ln.get("text")
        if text:
            chunks = captions.split_chunks(text, C["max_words"])
            if "cuts" in ln:
                cuts = ln["cuts"] if isinstance(ln["cuts"], list) else [ln["cuts"]]
                if len(cuts) != len(chunks) - 1:
                    die(f"{what}.cuts needs {len(chunks) - 1} time(s) (one between each pair of '|' chunks), got {len(cuts)}")
                b = [0.0] + [_num(c, f"{what}.cuts", 0, dur) for c in cuts] + [dur]
                if b != sorted(b):
                    die(f"{what}.cuts must be increasing")
            elif an:
                b = audio.chunk_bounds(an, [captions.chunk_weight(c) for c in chunks])
            else:
                w = [captions.chunk_weight(c) for c in chunks]
                b = [dur * sum(w[:k]) / sum(w) for k in range(len(w) + 1)]
            hold = _num(ln.get("hold", C["hold"]), f"{what}.hold", 0, 30)
            for k, ch in enumerate(chunks):
                caps.append({"text": ch, "who": who, "t0": at + b[k] - C["lead"],
                             "t1": at + b[k + 1] + (hold if k == len(chunks) - 1 else 0),
                             "pos": ln.get("pos"), "src": what})
        prev_end = end

    # ---- hook + silent captions
    extra = list(spec.get("captions") or [])
    hook = spec.get("hook")
    if hook:
        h = {"text": hook} if isinstance(hook, str) else dict(hook)
        h.setdefault("who", "hook")
        h.setdefault("at", 0)
        if "end" not in h and "dur" not in h:
            h["end"] = min(2.5, T)
        extra.insert(0, h)
    for i, c in enumerate(extra):
        what = f"captions[{i}]"
        _keys(c, CAP_KEYS, what)
        if not c.get("text"):
            die(f"{what} needs \"text\"")
        at = _num(c.get("at", 0), f"{what}.at", 0)
        end = _num(c["end"], f"{what}.end", 0) if "end" in c else at + _num(c.get("dur", 2.0), f"{what}.dur", 0.05)
        for ch in captions.split_chunks(c["text"], 99):
            caps.append({"text": ch, "who": c.get("who", "default"), "t0": at, "t1": end,
                         "pos": c.get("pos"), "src": what})

    for c in caps:
        try:
            c["y"] = captions.caption_y(c["pos"], style)
        except ValueError as e:
            die(f"{c['src']}: {e}")
        c["t0"], c["t1"] = max(0.0, c["t0"]), min(T, c["t1"])
    caps.sort(key=lambda c: (round(c["y"], 3), c["t0"]))
    for a, b in zip(caps, caps[1:]):                    # one caption at a time per position
        if round(a["y"], 3) == round(b["y"], 3) and a["t1"] > b["t0"]:
            if (b["t0"] - a["t0"]) < 0.5 * (a["t1"] - a["t0"]) and a["src"] != b["src"]:
                warn.append(f"caption \"{a['text']}\" is cut short at {ts(b['t0'])} by \"{b['text']}\"")
            a["t1"] = b["t0"]
    caps = sorted((c for c in caps if c["t1"] - c["t0"] >= 0.06), key=lambda c: c["t0"])

    # ---- effects
    flashes = []
    for i, f in enumerate(spec.get("fx") or []):
        what = f"fx[{i}]"
        _keys(f, {"at", "type", "dur", "amount"}, what)
        at = _num(f.get("at"), f"{what}.at", 0, T)
        if f.get("type") == "flash":
            flashes.append({"at": at, "dur": _num(f.get("dur", 0.25), f"{what}.dur", 0.03, 3),
                            "amount": _num(f.get("amount", 0.6), f"{what}.amount", 0, 1)})
        elif f.get("type") == "shake":
            d = _num(f.get("dur", 0.5), f"{what}.dur", 0.05, 10)
            amt = _num(f.get("amount", 1.0), f"{what}.amount", 0, 5)
            for s in segs:
                if at < s["t1"] and at + d > s["t0"]:
                    s["shakes"].append((at - s["t0"], d, amt))
        else:
            die(f"{what}.type must be 'flash' or 'shake'")

    sfx = []
    for i, s in enumerate(spec.get("sfx") or []):
        what = f"sfx[{i}]"
        _keys(s, {"at", "name", "file", "gain"}, what)
        item = {"at": _num(s.get("at"), f"{what}.at", 0, T), "gain": _num(s.get("gain", 0), f"{what}.gain", -40, 24)}
        if "file" in s:
            item["path"] = find_audio(s["file"], found, folder, what)["path"]
        elif s.get("name") in SFX_NAMES:
            item["name"] = s["name"]
        else:
            die(f"{what}: give \"name\" (one of {sorted(SFX_NAMES)}) or \"file\"")
        sfx.append(item)

    music = None
    if spec.get("music"):
        m = {"file": spec["music"]} if isinstance(spec["music"], str) else dict(spec["music"])
        _keys(m, {"file", "gain", "start"}, "music")
        music = {"path": find_audio(m["file"], found, folder, "music")["path"],
                 "gain": _num(m.get("gain", 0), "music.gain", -40, 24),
                 "start": _num(m.get("start", 0), "music.start", 0)}

    cta = None
    if spec.get("cta"):
        c = {} if spec["cta"] is True else dict(spec["cta"])
        _keys(c, {"at", "y"}, "cta")
        f = asset(style["cta"]["file"])
        if f.is_file():
            info = probe(f)
            at = min(_num(c.get("at", T * 0.45), "cta.at", 0, T), max(0.0, T - 0.5))
            yoff = _num(c.get("y", 0), "cta.y", -0.2, 0.7)
            cta = {"path": f, "at": at, "dur": min(info["duration"], T - at), "has_audio": info["has_audio"], "y": yoff}
            lo, hi = yoff + 0.08, yoff + 0.33          # the graphic sits in the top third of its frame
            hit = [c for c in caps if lo < c["y"] < hi and c["t0"] < at + cta["dur"] - 0.3 and c["t1"] > at + 0.3]
            if hit:
                warn.append(f"cta ({ts(at)}-{ts(at + cta['dur'])}) overlaps caption \"{hit[0]['text']}\" - "
                            f"move cta.at to a gap, or push it down with \"y\": 0.5 (fraction of frame height)")
        else:
            warn.append(f"cta skipped: {f} not found (set cta.file in style.json)")

    name = re.sub(r"[^\w\-]+", "_", spec.get("name") or folder.name).strip("_") or "short"
    return {"name": name, "folder": folder, "work": folder / "_sm", "style": style, "spec": spec,
            "clips": clips, "segs": segs, "fps": fps, "pfps": pfps, "T": T, "voices": voices,
            "caps": caps, "flashes": flashes, "sfx": sfx, "music": music, "cta": cta,
            "warn": warn, "found": found}


def describe(plan):
    """Compact human/model readable summary of the resolved plan."""
    out = [f"PLAN {plan['name']}  {ts(plan['T'])}s @ {plan['fps']}fps"]
    out.append("TIMELINE (final time <- clip source time)")
    for s in plan["segs"]:
        o = []
        if s["speed"] != 1:
            o.append(f"speed {s['speed']:g}")
        if s["z0"] != 1 or s["z1"] != 1:
            o.append(f"zoom {s['z0']:g}>{s['z1']:g}")
        if s["look"]:
            o.append(s["look"])
        if s["hold"]:
            o.append(f"hold {s['hold']:g}")
        if s["mute"]:
            o.append("mute")
        if s["shakes"]:
            o.append("shake")
        out.append(f"  {ts(s['t0']):>6}-{ts(s['t1']):<6} <- {s['clip']} {ts(s['in'])}-{ts(s['out'])}  {' '.join(o)}")
    if plan["voices"]:
        out.append("VOICE")
        for v in plan["voices"]:
            out.append(f"  {ts(v['at']):>6}-{ts(v['at'] + v['dur']):<6} {v['who']:<9} {v['path'].name[:60]}")
    if plan["caps"]:
        out.append("CAPTIONS")
        for c in plan["caps"]:
            out.append(f"  {ts(c['t0']):>6}-{ts(c['t1']):<6} {c['who']:<9} {c['text']}")
    for s in plan["sfx"]:
        out.append(f"SFX    {ts(s['at']):>6} {s.get('name') or s['path'].name}")
    for f in plan["flashes"]:
        out.append(f"FLASH  {ts(f['at']):>6}")
    if plan["cta"]:
        out.append(f"CTA    {ts(plan['cta']['at']):>6}-{ts(plan['cta']['at'] + plan['cta']['dur'])}")
    for w in plan["warn"]:
        out.append("WARNING: " + w)
    return "\n".join(out)


__all__ = ["discover", "resolve", "describe", "load_spec", "SMError"]
