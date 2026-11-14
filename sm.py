#!/usr/bin/env python3
"""Shorts Maker - turn a folder (clip + voice lines + short.json) into a finished
YouTube Short and thumbnail in the channel's house style.

  python sm.py scan    <folder>              look at the folder, build contact sheets, draft short.json
  python sm.py frames  <folder> <clip> <t0> <t1>   close-up strip of a clip between two source times
  python sm.py preview <folder>              fast 540p preview + review sheet (checks short.json)
  python sm.py render  <folder> [--res 4k]   final video (resumable: run again if it says PARTIAL)
  python sm.py thumb   <folder>              thumbnail from the "thumbnail" block
  python sm.py clean   <folder>              free the space used by cached render chunks
  python sm.py doctor                        check ffmpeg / GPU / python packages

See README.md for the short.json format."""
import argparse
import sys
from pathlib import Path

try:
    import numpy  # noqa: F401
    import PIL    # noqa: F401
except ImportError as e:                                    # pragma: no cover
    sys.exit(f"Missing python package ({e.name}). Run:  pip install pillow numpy")

from smlib import audio, spec as specmod, thumb, video
from smlib.style import RES, load_style
from smlib.util import SMError, default_budget, elapsed, load_json, probe, save_json, say, tool, ts


def _rel(path, folder):
    """Short path for output: relative to the short's folder when possible."""
    try:
        return Path(path).relative_to(folder).as_posix()
    except ValueError:
        return str(path)


def _folder(p):
    f = Path(p).expanduser().resolve()
    if not f.is_dir():
        raise SMError(f"folder not found: {f}")
    return f


def cmd_scan(a):
    folder = _folder(a.folder)
    style = load_style()
    found = specmod.discover(folder, style)
    work = folder / "_sm"
    work.mkdir(exist_ok=True)
    say(f"SHORT  {folder.name}   (paths below are inside this folder)")
    say("CLIPS")
    clips = []
    for v in found["videos"]:
        info = probe(v["path"])
        fps = min(60, round(info["fps"]) or 30)
        box = None if (a.only and a.only.lower() not in v["path"].name.lower()) else video.detect_bars(v["path"], info, work)
        clips.append({"key": v["key"], "path": v["path"], "info": info, "fit": "crop", "cx": 0.5, "box": box,
                      "pfps": fps // 2 if fps >= 48 and fps % 2 == 0 else fps})
        say(f"  {v['key']}  {v['path'].name}  {info['width']}x{info['height']} {info['fps']:.0f}fps "
            f"{info['duration']:.2f}s audio:{'yes' if info['has_audio'] else 'no'}"
            + (f"  black bars found: picture is {box[0]}x{box[1]}, zoomed to fill (clip option \"fit\": \"blur\" "
               f"keeps it whole, \"bars\": \"keep\" leaves the bars)" if box else ""))
    if not clips:
        say("  (no video files found in this folder)")
    say("VOICE  (#  who  seconds  [tags]  text-from-filename)")
    for v in found["voices"]:
        an = audio.analyze_voice(v["path"])
        v["dur"] = an["dur"]
        gaps = " ".join(f"{a0:.2f}-{a1:.2f}" for a0, a1 in audio.pauses(an, 0.12))
        say(f"  {v['idx']:>2}  {v['who'] or '?':<9} {v['dur']:.2f}  [{v['tags']}]  {v['hint']}"
            + (f"   pauses: {gaps}" if gaps else ""))
    if not found["voices"]:
        say("  (none - put voice mp3 files in the folder or its audio/ subfolder)")
    for s in found["sfx"]:
        say(f"SFX    {s['path'].parent.name}/{s['path'].name}  {probe(s['path'])['duration']:.1f}s")
    say(f"BUILT-IN SFX  {' '.join(sorted(audio.SYNTH))}")

    pending = False
    for c in clips:
        if a.only and a.only.lower() not in c["path"].name.lower():
            continue
        p = video.ensure_proxy(work, c, c["pfps"], default_budget())
        if p is None:
            pending = True
            break
        out = work / f"sheet_{c['key']}.jpg"
        _, step = video.clip_sheet(p, out)
        say(f"SHEET  {_rel(out, folder)}  (clip {c['key']}: one frame every {step:g}s, labels = source seconds)")
        if elapsed() > default_budget() * 0.8:
            pending = any(not (work / f"sheet_{x['key']}.jpg").exists() for x in clips)
            break

    sp = folder / "short.json"
    if sp.exists():
        say("SPEC   short.json already exists (not changed)")
    elif clips:
        seen, lines = {}, []
        for v in found["voices"]:                         # newest take of a repeated line wins
            seen[(v["who"], v["hint"].lower())] = v
        for i, v in enumerate(sorted(seen.values(), key=lambda v: v["idx"])):
            ln = {"who": v["who"] or "default", "audio": v["idx"], "text": v["hint"]}
            if i == 0:
                ln["at"] = 0.5
            lines.append(ln)
        c0 = clips[0]
        draft = {"name": folder.name, "clips": {c["key"]: c["path"].name for c in clips},
                 "timeline": [[c0["key"], 0, round(c0["info"]["duration"], 2)]],
                 "hook": "", "lines": lines,
                 "thumbnail": {"clip": c0["key"], "t": round(c0["info"]["duration"] * 0.6, 1),
                               "title": ["LINE ONE", "LINE TWO?!"]}}
        save_json(sp, draft)
        say("SPEC   draft short.json written (edit it, then run preview)")
    say("STATUS: PARTIAL - run scan again to finish the proxies" if pending else "STATUS: DONE")


def cmd_frames(a):
    folder = _folder(a.folder)
    plan_clips = None
    try:
        plan = specmod.resolve(folder)
        plan_clips, pfps = plan["clips"], plan["pfps"]
    except SMError:
        pass
    if plan_clips is None or a.clip not in plan_clips:
        style = load_style()
        found = specmod.discover(folder, style)
        v = next((v for v in found["videos"] if v["key"] == a.clip), None)
        if not v:
            raise SMError(f"unknown clip '{a.clip}'")
        info = probe(v["path"])
        fps = min(60, round(info["fps"]) or 30)
        clip = {"path": v["path"], "info": info, "fit": "crop", "cx": 0.5,
                "box": video.detect_bars(v["path"], info, folder / "_sm")}
        pfps = fps // 2 if fps >= 48 and fps % 2 == 0 else fps
    else:
        clip = plan_clips[a.clip]
    work = folder / "_sm"
    p = video.ensure_proxy(work, clip, pfps, default_budget())
    if p is None:
        say("STATUS: PARTIAL - run again")
        return
    n = max(2, min(20, a.n))
    times = [a.t0 + (a.t1 - a.t0) * i / (n - 1) for i in range(n)]
    out = work / "frames.jpg"
    video.sheet(p, times, out, tile_w=216, cols=10)
    say(f"FRAMES {_rel(out, folder)}  ({n} frames {a.t0:g}-{a.t1:g}s of clip {a.clip})")
    say("STATUS: DONE")


def _proxies(plan):
    for key in dict.fromkeys(s["clip"] for s in plan["segs"]):
        if video.ensure_proxy(plan["work"], plan["clips"][key], plan["pfps"], default_budget()) is None:
            say("STATUS: PARTIAL - proxies still building, run the same command again")
            return False
    return True


def cmd_preview(a):
    plan = specmod.resolve(_folder(a.folder))
    plan["work"].mkdir(exist_ok=True)
    say(specmod.describe(plan))
    if not _proxies(plan):
        return
    wav = plan["work"] / "preview_mix.wav"
    rep = audio.build_mix(plan, wav)
    W, H = RES["preview"]
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-g", str(plan["pfps"]), "-pix_fmt", "yuv420p"]
    files = video.render_video(plan, W, H, plan["pfps"], False, enc, 1e9, 1e9, "preview")
    out = video.assemble(plan, files, wav, plan["work"] / "preview.mp4", "128k")
    times, labels = video.review_times(plan)
    sheet = video.sheet(out, times, plan["work"] / "preview.jpg", labels, tile_w=270, cols=8)
    say(f"AUDIO  loudness {rep['lufs_out']} LUFS (gain {rep['gain_db']:+} dB)")
    say(f"PREVIEW {_rel(out, plan['folder'])}")
    say(f"SHEET  {_rel(sheet, plan['folder'])}  (one tile per caption / cut - look at this to check the edit)")
    say("STATUS: DONE")


def cmd_render(a):
    plan = specmod.resolve(_folder(a.folder))
    plan["work"].mkdir(exist_ok=True)
    style = plan["style"]
    res = str(a.res or style["video"]["res"]).lower()
    if res not in RES or res == "preview":
        raise SMError("--res must be one of: 1080, 1440, 4k, 8k")
    W, H = RES[res]
    for w in plan["warn"]:
        say("WARNING: " + w)
    name, enc = video.encoder(style, res, a.codec, plan["fps"])
    say(f"RENDER {plan['name']}  {W}x{H} @ {plan['fps']}fps  {ts(plan['T'])}s  encoder={name}")
    wav = plan["work"] / "final_mix.wav"
    rep = audio.build_mix(plan, wav)
    chunk = float(a.chunk or style["video"]["chunk_s"][res])
    try:
        files = video.render_video(plan, W, H, plan["fps"], True, enc, chunk, default_budget(), f"{res}_{name}",
                                   video.low_memory(res) and name != "nvenc")
    except SMError as e:
        if name != "nvenc" or (a.codec or style["video"]["codec"]) != "auto":
            raise
        say(f"  GPU encoder failed ({str(e).splitlines()[-1].strip()}) - falling back to CPU x264")
        name, enc = video.encoder(style, res, "x264", plan["fps"])
        files = video.render_video(plan, W, H, plan["fps"], True, enc, chunk, default_budget(), f"{res}_{name}",
                                   video.low_memory(res))
    if files is None:
        return
    out = plan["folder"] / f"{plan['name']}_FINAL_{res.upper()}.mp4"
    video.assemble(plan, files, wav, out)
    info = probe(out)
    problems = []
    if (info["width"], info["height"]) != (W, H):
        problems.append(f"size is {info['width']}x{info['height']}")
    if abs(info["duration"] - plan["T"]) > 0.15:
        problems.append(f"duration {info['duration']:.2f}s, expected {plan['T']:.2f}s")
    if not info["has_audio"]:
        problems.append("no audio")
    srt = plan["folder"] / f"{plan['name']}_captions.srt"
    video.write_srt(plan, srt)
    times, labels = video.review_times(plan, 6 if res == "8k" else 12)
    sheet = video.sheet(out, times, plan["work"] / "final.jpg", labels, tile_w=270, cols=6)
    say(f"FINAL  {out.name}  {info['width']}x{info['height']} {info['duration']:.2f}s "
        f"{out.stat().st_size / 1e6:.0f}MB  {rep['lufs_out']} LUFS")
    say(f"SHEET  {_rel(sheet, plan['folder'])}")
    say(f"SRT    {srt.name}")
    say("STATUS: " + ("CHECK - " + "; ".join(problems) if problems else "DONE"))


def cmd_thumb(a):
    plan = specmod.resolve(_folder(a.folder))
    out = plan["folder"] / f"{plan['name']}_thumbnail.jpg"
    thumb.make_thumbnail(plan, out)
    say(f"THUMB  {out.name}")
    say("STATUS: DONE")


def cmd_clean(a):
    """Free the disk space used by cached render chunks (the finished video is kept)."""
    work = _folder(a.folder) / "_sm"
    freed = 0
    for f in sorted(work.glob("chunks_*/*")) + sorted(work.glob("*.wav")):
        if not f.is_file():
            continue
        freed += f.stat().st_size
        try:
            f.unlink()
        except OSError:                       # deleting not allowed here: empty the file instead
            f.write_bytes(b"")
    say(f"CLEAN  freed {freed / 1e6:.0f} MB in _sm (proxy and sheets kept)")
    say("STATUS: DONE")


def cmd_doctor(a):
    import PIL
    import numpy
    say(f"python  {sys.version.split()[0]}   pillow {PIL.__version__}   numpy {numpy.__version__}")
    say(f"ffmpeg  {tool('ffmpeg')}")
    say(f"ffprobe {tool('ffprobe')}")
    say("GPU     " + ("NVIDIA hevc_nvenc available - fast 8K renders" if video.nvenc_ok()
                      else "no NVIDIA encoder found - renders use the CPU (x264)"))
    st = load_style()
    for k, f in st["fonts"].items():
        from smlib.style import asset
        say(f"font    {k}: {'ok' if asset(f).is_file() else 'MISSING ' + str(asset(f))}")
    say("STATUS: DONE")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("folder")
    p.add_argument("--only", help="only build proxies for clips whose name contains this")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("frames")
    p.add_argument("folder")
    p.add_argument("clip")
    p.add_argument("t0", type=float)
    p.add_argument("t1", type=float)
    p.add_argument("--n", type=int, default=10)
    p.set_defaults(fn=cmd_frames)
    p = sub.add_parser("preview")
    p.add_argument("folder")
    p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("render")
    p.add_argument("folder")
    p.add_argument("--res", help="1080 | 1440 | 4k | 8k (default from style.json)")
    p.add_argument("--codec", help="auto | nvenc | x264 | x265")
    p.add_argument("--chunk", help="seconds per render chunk (advanced)")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("thumb")
    p.add_argument("folder")
    p.set_defaults(fn=cmd_thumb)
    p = sub.add_parser("clean")
    p.add_argument("folder")
    p.set_defaults(fn=cmd_clean)
    p = sub.add_parser("doctor")
    p.set_defaults(fn=cmd_doctor)
    a = ap.parse_args()
    try:
        a.fn(a)
    except SMError as e:
        say(f"ERROR: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
