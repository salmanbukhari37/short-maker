"""Shared helpers: ffmpeg/ffprobe wrappers, audio I/O, small utilities."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent      # the shorts-maker folder
SR = 48000                                         # working audio sample rate
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
_START = time.time()


class SMError(Exception):
    """A problem the user/model can fix (bad spec, missing file...)."""


def die(msg):
    raise SMError(msg)


def elapsed():
    return time.time() - _START


def default_budget():
    """Seconds one invocation may use. The Claude desktop sandbox kills every
    process when a call ends (max 180 s), so there we stop early and resume."""
    env = os.environ.get("SM_BUDGET")
    if env:
        return float(env)
    return 140.0 if os.environ.get("SANDBOX_RUNTIME") else 1e9


def ram_gb():
    """Physical memory in GB (assume plenty if it cannot be read)."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ("total", "avail", "tp", "ap", "tv", "av", "ext")]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 2 ** 30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except Exception:
        return 64.0


_TOOLS = {}


def tool(name):
    if name in _TOOLS:
        return _TOOLS[name]
    exe = name + (".exe" if os.name == "nt" else "")
    cands = [os.environ.get("SM_" + name.upper()), str(ROOT / "bin" / exe), shutil.which(name)]
    for c in cands:
        if c and Path(c).exists():
            _TOOLS[name] = c
            return c
    die(f"{name} not found. Install ffmpeg (Windows: 'winget install Gyan.FFmpeg') "
        f"or put {exe} in {ROOT / 'bin'}")


def run(args, check=True, binary=False):
    """Run a command, return stdout. Raises SMError with the stderr tail on failure."""
    args = [str(a) for a in args]
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-12:]
        if p.returncode < 0 or p.returncode == 137:
            tail.append(f"the process was killed (signal {abs(p.returncode)}) - usually out of memory. "
                        "Try a lower --res, or render on the PC with RENDER_8K_GPU.bat")
        raise SMError("command failed: " + " ".join(args[:6]) + " ...\n  " + "\n  ".join(tail))
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def run_err(args):
    """Run and return stderr text (ffmpeg prints measurements there)."""
    p = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stderr.decode("utf-8", "replace")


def ffmpeg(*args, **kw):
    return run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", *args], **kw)


_PROBE = {}


def probe(path):
    """-> dict(width,height,fps,duration,has_audio,has_video,codec,pix_fmt)"""
    path = Path(path)
    key = (str(path), path.stat().st_mtime_ns)
    if key in _PROBE:
        return _PROBE[key]
    out = run([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    j = json.loads(out)
    info = {"has_audio": False, "has_video": False, "width": 0, "height": 0, "fps": 0.0,
            "codec": "", "pix_fmt": "", "duration": float(j.get("format", {}).get("duration", 0) or 0)}
    for s in j.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"] \
                and not s.get("disposition", {}).get("attached_pic"):
            info["has_video"] = True
            w, h = int(s["width"]), int(s["height"])
            rot = 0
            for sd in s.get("side_data_list", []):
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            if abs(rot) in (90, 270):
                w, h = h, w
            info.update(width=w, height=h, codec=s.get("codec_name", ""), pix_fmt=s.get("pix_fmt", ""))
            num, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").split("/")
            info["fps"] = float(num) / float(den) if float(den) else 0.0
            if s.get("duration"):
                info["vduration"] = float(s["duration"])
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    _PROBE[key] = info
    return info


def read_audio(path, ss=None, t=None, af=None):
    """Decode (part of) any media file to float32 stereo at SR. -> array (n, 2)"""
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.6f}"]
    if t is not None:
        cmd += ["-t", f"{t:.6f}"]
    cmd += ["-i", path, "-vn"]
    if af:
        cmd += ["-af", af]
    cmd += ["-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    raw = run(cmd, binary=True)
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def write_wav(path, x):
    x = np.clip(x, -1.0, 1.0)
    pcm = (x * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def db2lin(db):
    return 10.0 ** (db / 20.0)


def sha(*parts, n=10):
    h = hashlib.sha1()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:n]


def file_sig(path):
    st = Path(path).stat()
    return (st.st_size, st.st_mtime_ns)


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        die(f"{Path(path).name} is not valid JSON: line {e.lineno} col {e.colno}: {e.msg}")


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def ts(t):
    """seconds -> compact '12.35'"""
    return f"{t:.2f}"


def say(*a):
    print(*a)
    sys.stdout.flush()
