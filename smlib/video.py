"""Video: proxies, contact sheets, and the chunked/resumable renderer.

The renderer works on fixed time windows ("chunks") of the final timeline. Each
chunk is one ffmpeg run that reads only the source ranges it needs, so a render
can stop and resume (needed where one command may only run ~3 minutes) and an
edit to one caption only re-renders the chunk it sits in."""
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import captions
from .style import RES
from .util import (die, elapsed, ffmpeg, file_sig, probe, ram_gb, run, say, sha, tool, ts)

PW, PH = RES["preview"]
LOOKS = {
    "drama": "eq=saturation=0.5:contrast=1.1:brightness=-0.04,vignette=angle=PI/4.2",
    "dark": "eq=brightness=-0.12:saturation=0.85,vignette=angle=PI/4",
    "punch": "eq=saturation=1.22:contrast=1.08",
    "warm": "eq=saturation=1.12,colorbalance=rs=0.06:gs=0.01:bs=-0.06:rm=0.04:bm=-0.04",
    "bw": "hue=s=0",
}


def _f(v):
    return f"{v:.5f}".rstrip("0").rstrip(".")


def _write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def _read(path):
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ------------------------------------------------------------------- fitting

def fit_chain(clip, W, H, uid="0"):
    """Filters that turn any source frame into a WxH 9:16 frame. -> (chain, complex?)"""
    w, h = clip["info"]["width"], clip["info"]["height"]
    if (w, h) == (W, H):
        return []
    if clip["fit"] == "blur" and w * H > h * W * 1.02:      # source wider than 9:16
        u = uid
        return [f"split[fa{u}][fb{u}];[fa{u}]scale={W // 8}:{H // 8}:force_original_aspect_ratio=increase,"
                f"crop={W // 8}:{H // 8},boxblur=6:2,scale={W}:{H}:flags=bilinear,eq=brightness=-0.12[fbg{u}];"
                f"[fb{u}]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic[ffg{u}];"
                f"[fbg{u}][ffg{u}]overlay=(W-w)/2:(H-h)/2"]
    return [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic",
            f"crop={W}:{H}:(iw-{W})*{_f(clip['cx'])}:(ih-{H})/2"]


# ------------------------------------------------------------------- proxies

def proxy_path(work, clip, pfps):
    return Path(work) / f"proxy_{sha(file_sig(clip['path']), clip['fit'], clip['cx'], PW, PH, pfps)}.mp4"


def ensure_proxy(work, clip, pfps, budget):
    """Small 540x960 copy of a clip for fast previews. Built in 30 s parts so it
    can resume. -> path, or None if the time budget ran out (call again)."""
    out = proxy_path(work, clip, pfps)
    if _read(str(out) + ".ok") == "ok":
        return out
    work = Path(work)
    work.mkdir(exist_ok=True)
    dur = clip["info"]["duration"]
    part_len = 30.0
    n = max(1, int(dur / part_len + 0.999))
    chain = ",".join(fit_chain(clip, PW, PH) + [f"fps={pfps}", "format=yuv420p", "setsar=1"])
    parts = []
    for k in range(n):
        part = out if n == 1 else Path(str(out)[:-4] + f"_p{k:03d}.mp4")
        parts.append(part)
        if _read(str(part) + ".ok") == "ok":
            continue
        if k > 0 and elapsed() > budget * 0.6:
            say(f"  proxy {clip['path'].name}: {k}/{n} parts done")
            return None
        ffmpeg("-ss", _f(k * part_len), "-t", _f(part_len), "-i", clip["path"], "-an",
               "-filter_complex", f"[0:v]{chain}[v]", "-map", "[v]",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-g", str(pfps), part)
        _write(str(part) + ".ok", "ok")
    if n > 1:
        lst = Path(str(out)[:-4] + "_list.txt")
        _write(lst, "".join(f"file '{p.name}'\n" for p in parts))
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
        _write(str(out) + ".ok", "ok")
    return out


# -------------------------------------------------------------------- sheets

def _label(draw, xy, text, font):
    x, y = xy
    w = draw.textlength(text, font=font)
    draw.rectangle((x, y, x + w + 10, y + font.size + 8), fill=(0, 0, 0, 255))
    draw.text((x + 5, y + 3), text, font=font, fill=(255, 235, 60, 255))


def sheet(video, times, out, labels=None, tile_w=216, cols=10):
    """Grab one frame per time and tile them with time labels."""
    info = probe(video)
    tile_h = round(tile_w * info["height"] / info["width"] / 2) * 2
    rows = (len(times) + cols - 1) // cols
    im = Image.new("RGB", (cols * tile_w if rows > 1 else len(times) * tile_w, rows * tile_h), (20, 20, 20))
    d = ImageDraw.Draw(im)
    fnt = captions.font("fonts/Montserrat-Bold.ttf", max(14, tile_w // 11))
    for i, t in enumerate(times):
        t = max(0.0, min(t, info["duration"] - 0.05))
        raw = run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-ss", _f(t), "-i", video,
                   "-frames:v", "1", "-vf", f"scale={tile_w}:{tile_h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                  binary=True, check=False)
        x, y = (i % cols) * tile_w, (i // cols) * tile_h
        if len(raw) == tile_w * tile_h * 3:
            im.paste(Image.frombytes("RGB", (tile_w, tile_h), raw), (x, y))
        _label(d, (x + 3, y + 3), labels[i] if labels else ts(t), fnt)
    im.save(out, quality=82)
    return out


def clip_sheet(proxy, out, t0=0.0, t1=None, max_tiles=60):
    dur = probe(proxy)["duration"]
    t1 = min(dur, t1 if t1 is not None else dur)
    span = max(0.1, t1 - t0)
    step = 0.5
    while span / step > max_tiles:
        step *= 2
    if span <= 6:
        step = max(1 / 30, span / 20)
    times = [t0 + i * step for i in range(int(span / step + 1e-6) + 1) if t0 + i * step < t1 - 0.01]
    return sheet(proxy, times, out), step


# ------------------------------------------------------------------ encoders

_NVENC = None


def nvenc_ok():
    global _NVENC
    if _NVENC is None:
        p = subprocess.run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                            "color=black:s=640x640:r=30:d=0.2", "-c:v", "hevc_nvenc", "-f", "null", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _NVENC = p.returncode == 0
    return _NVENC


def low_memory(res):
    """8K frames are ~50 MB each; on small machines keep decoder/encoder buffers minimal."""
    return res == "8k" and ram_gb() < 8


def encoder(style, res, codec, fps):
    """-> (name, ffmpeg video-encoder args)"""
    V = style["video"]
    codec = codec or V["codec"]
    if codec == "auto":
        codec = "nvenc" if nvenc_ok() else "x264"
    crf = V["crf"][res] if isinstance(V["crf"], dict) else V["crf"]
    if codec == "nvenc":
        return "nvenc", ["-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(V["nvenc_cq"]),
                         "-b:v", "0", "-g", str(fps), "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    if codec == "x265":
        return "x265", ["-c:v", "libx265", "-preset", "fast", "-crf", str(crf + 3), "-g", str(fps),
                        "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
    if codec != "x264":
        die(f"unknown codec '{codec}' (auto | nvenc | x264 | x265)")
    args = ["-c:v", "libx264", "-preset", V["x264_preset"], "-crf", str(crf), "-g", str(fps), "-pix_fmt", "yuv420p"]
    if low_memory(res):
        args += ["-threads", "2", "-x264-params", "rc-lookahead=2:sync-lookahead=0:ref=1:bframes=0:sliced-threads=1"]
        return "x264lm", args
    return "x264", args


# -------------------------------------------------------------- caption PNGs

def caption_pngs(plan, W, H):
    """Render every caption once for this output size. -> list aligned with plan['caps']"""
    st = plan["style"]
    cdir = plan["work"] / f"caps_{W}"
    cdir.mkdir(parents=True, exist_ok=True)
    out = []
    for c in plan["caps"]:
        key = sha(c["text"], c["who"], st["caption"], st["speakers"].get(c["who"]), st["speakers"]["default"],
                  st["fonts"], st["text_color"], st["stroke_color"], W)
        p = cdir / f"{key}.png"
        if p.exists():
            with Image.open(p) as im:
                size = im.size
        else:
            im, _ = captions.render_caption(c["text"], c["who"], st, W)
            im.save(p)
            size = im.size
        x = (W - size[0]) // 2
        y = round(c["y"] * H - size[1] / 2)
        out.append({"png": p, "x": x, "y": max(0, min(H - size[1], y)), "w": size[0], "h": size[1]})
    return out


# ------------------------------------------------------------- chunk builder

def build_chunk(plan, c0, c1, W, H, fps, final, caps_png, lowmem=False):
    """ffmpeg inputs + filter graph for final-timeline window [c0, c1).
    -> (input args, graph, cache-key material)"""
    inputs, graph, keyp, labels = [], [], [], []
    ni = 0
    for s in plan["segs"]:
        if s["t1"] <= c0 + 1e-6 or s["t0"] >= c1 - 1e-6:
            continue
        clip = plan["clips"][s["clip"]]
        a = max(c0, s["t0"]) - s["t0"]                  # window inside this segment (output seconds)
        b = min(c1, s["t1"]) - s["t0"]
        n = round((b - a) * fps)
        if n <= 0:
            continue
        seg_dur = s["t1"] - s["t0"]
        a_c = max(0.0, min(a, s["content"] - 1.0 / fps))       # where to start reading content
        ss = s["in"] + a_c * s["speed"]
        read = (max(1.0 / fps, min(b, s["content"]) - a_c) + 2.0 / fps) * s["speed"]
        src = clip["path"] if final else proxy_path(plan["work"], clip, plan["pfps"])
        inputs += (["-threads", "1"] if lowmem else []) + ["-ss", _f(ss), "-t", _f(read), "-i", str(src)]
        keyp.append((file_sig(clip["path"]), _f(ss), _f(read)))
        ch = (fit_chain(clip, W, H, str(ni)) if final else [])
        ch += [f"setpts=(PTS-STARTPTS)/{_f(s['speed'])}", f"fps={fps}", "format=yuv420p",
               f"tpad=stop_mode=clone:stop_duration={_f(b - a + 1)}", f"trim=end_frame={n}", "setpts=PTS-STARTPTS"]
        shakes = [(ws, wd, amt) for ws, wd, amt in s["shakes"] if ws < b and ws + wd > a]
        if s["z0"] != 1 or s["z1"] != 1 or shakes:
            # tau = t + a is the time inside the segment
            z = f"({_f(s['z0'])}+{_f(s['z1'] - s['z0'])}*min(1,(t+{_f(a)})/{_f(seg_dur)}))"
            env = [f"{_f(amt)}*between(t+{_f(a)},{_f(ws)},{_f(ws + wd)})*(1-(t+{_f(a)}-{_f(ws)})/{_f(wd)})"
                   for ws, wd, amt in shakes]
            e = "(" + "+".join(env) + ")" if env else "0"
            zt = f"{z}*(1+0.035*{e})"
            jx = f"{_f(0.012 * W)}*{e}*sin(2*PI*17*t)" if env else "0"
            jy = f"{_f(0.012 * W)}*{e}*cos(2*PI*13*t)" if env else "0"
            graph.append(f"color=c=black:s={W}x{H}:r={fps}:d={_f(b - a)}[bg{ni}]")
            graph.append(f"[{ni}:v]" + ",".join(ch) +
                         f",scale=w='2*trunc({W}*{zt}/2)':h='2*trunc({H}*{zt}/2)':eval=frame:flags=bilinear[z{ni}]")
            ch = [f"[bg{ni}][z{ni}]overlay=x='min(0,max(-(w-W),-(w-W)*{_f(s['fx'])}+{jx}))':"
                  f"y='min(0,max(-(h-H),-(h-H)*{_f(s['fy'])}+{jy}))':shortest=1", "format=yuv420p"]
            head = ""
        else:
            head = f"[{ni}:v]"
        if s["look"]:
            ch.append(LOOKS[s["look"]])
        ch.append("setsar=1")
        graph.append(head + ",".join(ch) + f"[p{ni}]")
        labels.append(f"[p{ni}]")
        ni += 1
    if not labels:
        die(f"internal: empty chunk {c0}-{c1}")
    cur = "[vc]"
    if len(labels) == 1:
        graph.append(f"{labels[0]}null[vc]")
    else:
        graph.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vc]")
    step = 0

    def nxt(expr, extra_in=""):
        nonlocal cur, step
        step += 1
        new = f"[g{step}]"
        graph.append(f"{cur}{extra_in}{expr}{new}")
        cur = new

    grade = plan["style"]["video"].get("grade")
    if grade:
        if grade not in LOOKS:
            die(f"style video.grade '{grade}' unknown ({sorted(LOOKS)})")
        nxt(LOOKS[grade])
    for f in plan["flashes"]:
        if f["at"] < c1 and f["at"] + f["dur"] > c0:
            A = f["at"] - c0
            nxt(f"eq=eval=frame:brightness='{_f(f['amount'])}*(1-(t-({_f(A)}))/{_f(f['dur'])})':"
                f"enable='between(t,{_f(A)},{_f(A + f['dur'])})'")
    cta = plan["cta"]
    if cta and cta["at"] < c1 and cta["at"] + cta["dur"] > c0:
        A = cta["at"] - c0
        inputs += ["-ss", _f(max(0.0, -A)), "-i", str(cta["path"])]
        keyp.append((file_sig(cta["path"]), _f(A), cta["y"]))
        graph.append(f"[{ni}:v]scale={W}:{H}:flags=bilinear,setpts=PTS-STARTPTS+{_f(max(0.0, A))}/TB[cta]")
        nxt(f"overlay=0:{round(cta['y'] * H)}:eof_action=pass:"
            f"enable='between(t,{_f(max(0.0, A))},{_f(A + cta['dur'])})'", "[cta]")
        ni += 1
    pop = plan["style"]["caption"]["pop"]
    for c, p in zip(plan["caps"], caps_png):
        if c["t0"] >= c1 - 1e-6 or c["t1"] <= c0 + 1e-6:
            continue
        A, B = c["t0"] - c0, c["t1"] - c0
        inputs += ["-i", str(p["png"])]
        keyp.append((p["png"].name, p["x"], p["y"]))
        y = f"'{p['y']}+{_f(0.012 * H)}*pow(1-min(1,max(0,t-({_f(A)}))/0.09),2)'" if pop else str(p["y"])
        nxt(f"overlay=x={p['x']}:y={y}:enable='between(t,{_f(A)},{_f(B - 0.5 / fps)})'", f"[{ni}:v]")
        ni += 1
    graph.append(f"{cur}format=yuv420p[vout]")
    return inputs, ";".join(graph), keyp


def render_video(plan, W, H, fps, final, enc_args, chunk_len, budget, tag, lowmem=False):
    """Render all chunks (resumable). -> list of chunk files, or None if time ran out."""
    caps_png = caption_pngs(plan, W, H)
    cdir = plan["work"] / f"chunks_{tag}"
    cdir.mkdir(parents=True, exist_ok=True)
    T = plan["T"]
    wins, t = [], 0.0
    while t < T - 1e-6:
        wins.append((t, min(T, t + chunk_len)))
        t += chunk_len
    files, done, last = [], 0, 0.0
    for k, (c0, c1) in enumerate(wins):
        inputs, graph, keyp = build_chunk(plan, c0, c1, W, H, fps, final, caps_png, lowmem)
        key = sha(keyp, graph, enc_args, W, H, fps, n=16)
        out = cdir / f"c{k:03d}.mp4"
        files.append(out)
        if _read(str(out) + ".key") == key:
            continue
        if done and elapsed() + last * 1.25 > budget:
            say(f"STATUS: PARTIAL {k}/{len(wins)} chunks rendered - run the same command again to continue")
            return None
        _write(str(out) + ".key", "")
        t0 = time.time()
        ffmpeg(*inputs, "-filter_complex", graph, "-map", "[vout]", "-an", *enc_args,
               "-t", _f(c1 - c0), out)
        _write(str(out) + ".key", key)
        last = time.time() - t0
        done += 1
        say(f"  chunk {k + 1}/{len(wins)} ({ts(c0)}-{ts(c1)}s) {last:.0f}s")
    return files


def assemble(plan, files, wav, out, audio_bitrate="320k"):
    """Join chunks (no re-encode) and add the mixed audio."""
    lst = files[0].parent / "list.txt"
    _write(lst, "".join(f"file '{p.name}'\n" for p in files))
    hevc = probe(files[0])["codec"] == "hevc"
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", *(["-tag:v", "hvc1"] if hevc else []), "-c:a", "aac", "-b:a", audio_bitrate,
           "-ar", "48000", "-movflags", "+faststart", "-t", _f(plan["T"]), out)
    return out


def review_times(plan, max_tiles=24):
    """Moments worth looking at: every caption and every cut."""
    pts = [(c["t0"] + min(0.45, (c["t1"] - c["t0"]) / 2), c["who"][:3]) for c in plan["caps"]]
    pts += [(s["t0"] + 0.1, "cut") for s in plan["segs"]]
    pts += [(f["at"] + 0.04, "fx") for f in plan["flashes"]]
    if plan["cta"]:
        pts.append((plan["cta"]["at"] + plan["cta"]["dur"] / 2, "cta"))
    pts.sort()
    out = []
    for t, tag in pts:
        if out and t - out[-1][0] < 0.12:
            continue
        out.append((min(t, plan["T"] - 0.05), tag))
    if len(out) > max_tiles:
        stepn = len(out) / max_tiles
        out = [out[int(i * stepn)] for i in range(max_tiles)]
    return [t for t, _ in out], [f"{ts(t)} {tag}" for t, tag in out]


def write_srt(plan, path):
    def tc(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    rows = []
    for i, c in enumerate(plan["caps"], 1):
        text = captions.strip_emoji(c["text"]).replace("/", " ")
        rows.append(f"{i}\n{tc(c['t0'])} --> {tc(c['t1'])}\n{' '.join(text.split())}\n")
    _write(path, "\n".join(rows))
