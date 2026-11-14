"""Audio: voice analysis, caption timing from the voice, built-in sound effects
and the final mix (numpy; ffmpeg only decodes and does the loudness pass)."""
import re

import numpy as np

from .util import SR, db2lin, read_audio, run_err, tool, write_wav, ffmpeg

FRAME = SR // 100          # 10 ms analysis frames
_VOICE = {}


# -------------------------------------------------------------- voice analysis

def analyze_voice(path):
    """Trim silence around a voice line and find where speech is.
    -> dict(x=trimmed stereo audio, dur, voiced=bool per 10 ms frame, rms)"""
    key = str(path)
    if key in _VOICE:
        return _VOICE[key]
    x = read_audio(path)
    mono = x.mean(axis=1)
    n = len(mono) // FRAME
    if n < 3:
        an = {"x": x, "dur": len(x) / SR, "voiced": np.ones(max(1, n), bool), "rms": 0.05}
        _VOICE[key] = an
        return an
    fr = np.sqrt((mono[:n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1) + 1e-12)
    thr = max(fr.max() * db2lin(-32), db2lin(-52))
    voiced = fr > thr
    idx = np.flatnonzero(voiced)
    if len(idx) == 0:
        idx = np.array([0, n - 1])
    a = max(0, idx[0] - 2)                     # keep 20 ms before the first sound
    b = min(n, idx[-1] + 1 + 8)                # and 80 ms of tail
    x = x[a * FRAME:b * FRAME].copy()
    voiced = voiced[a:b]
    fade = min(len(x) // 4, SR // 200)
    if fade > 1:
        ramp = np.linspace(0, 1, fade)[:, None]
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    rms = float(np.sqrt((fr[a:b][voiced] ** 2).mean())) if voiced.any() else 0.05
    an = {"x": x, "dur": len(x) / SR, "voiced": voiced, "rms": rms}
    _VOICE[key] = an
    return an


def _smooth(voiced):
    """Drop tiny blips (breaths, clicks) and close tiny holes so only real pauses remain."""
    v = voiced.copy()

    def runs(arr):
        out, s = [], 0
        for i in range(1, len(arr) + 1):
            if i == len(arr) or arr[i] != arr[s]:
                out.append((s, i, bool(arr[s])))
                s = i
        return out
    for s, e, val in runs(v):
        if val and e - s <= 5:
            v[s:e] = False
    for s, e, val in runs(v):
        if not val and e - s <= 5 and s > 0 and e < len(v):
            v[s:e] = True
    return v, runs(v)


def pauses(an, min_len=0.07):
    """-> [(start, end)] seconds of the real pauses inside a voice line"""
    v, runs = _smooth(an["voiced"])
    return [(s * 0.01, e * 0.01) for s, e, val in runs
            if not val and (e - s) * 0.01 >= min_len and s > 0 and e < len(v)]


def chunk_bounds(an, weights):
    """Split a voice line into caption chunks. Each boundary is placed by how much
    has been spoken (text length) and snapped to a real pause in the voice when one
    is close, so captions change exactly when the next words start.
    -> [0, b1, ..., dur] seconds"""
    dur = an["dur"]
    n = len(weights)
    if n <= 1:
        return [0.0, dur]
    v, runs = _smooth(an["voiced"])
    cum = np.cumsum(v.astype(float))
    total = cum[-1] or 1.0
    gaps = [(s, e, cum[s - 1] / total) for s, e, val in runs
            if not val and e - s >= 7 and s > 0 and e < len(v)]       # pauses of 70 ms+
    bounds, last_gap = [0.0], -1
    for k in range(1, n):
        frac = sum(weights[:k]) / sum(weights)
        best = None
        for gi in range(last_gap + 1, len(gaps)):
            d = abs(gaps[gi][2] - frac)
            if d <= 0.22 and (best is None or d < best[0]):
                best = (d, gi)
        if best:
            last_gap = best[1]
            t = gaps[best[1]][1] * 0.01 - 0.02           # just before speech resumes
        else:
            t = float(np.searchsorted(cum, frac * total)) * 0.01
        bounds.append(t)
    bounds.append(dur)
    for k in range(1, n):                                # keep order and a minimum chunk length
        bounds[k] = min(max(bounds[k], bounds[k - 1] + 0.12), dur - 0.12 * (n - k))
    return bounds


# ------------------------------------------------------------ built-in effects

def _t(d):
    return np.arange(int(d * SR)) / SR


def _band(noise, lo, hi):
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(len(noise), 1 / SR)
    spec *= 1.0 / (1.0 + (f / max(hi, 1)) ** 6) * (1.0 - 1.0 / (1.0 + (f / max(lo, 1)) ** 6))
    return np.fft.irfft(spec, len(noise))


def _sweep(d, f0, f1, rng, bands=7):
    """Noise whose colour moves from f0 to f1 over its length."""
    n = int(d * SR)
    noise = rng.standard_normal(n)
    pos = np.linspace(0, 1, n)
    out = np.zeros(n)
    for b in range(bands):
        c = b / (bands - 1)
        fc = f0 * (f1 / f0) ** c
        w = np.clip(1 - np.abs(pos - c) * (bands - 1) / 1.5, 0, 1)
        out += _band(noise, fc * 0.7, fc * 1.4) * w
    return out


def sfx_boom(rng):
    t = _t(1.4)
    f = 36 + 80 * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.0)
    crack = _band(rng.standard_normal(len(t)), 40, 1400) * np.exp(-t * 11) * 0.9
    rumble = _band(rng.standard_normal(len(t)), 30, 220) * np.exp(-t * 2.2) * 0.5
    return np.tanh(1.6 * (body + crack + rumble))


def sfx_hit(rng):
    t = _t(0.45)
    f = 48 + 130 * np.exp(-t * 32)
    return np.tanh(2.0 * (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
                          + _band(rng.standard_normal(len(t)), 200, 3000) * np.exp(-t * 60) * 0.5))


def sfx_whoosh(rng):
    d = 0.55
    return _sweep(d, 250, 5000, rng) * np.sin(np.pi * np.linspace(0, 1, int(d * SR))) ** 2


def sfx_riser(rng):
    d = 1.5
    n = int(d * SR)
    p = np.linspace(0, 1, n)
    tone = np.sin(2 * np.pi * np.cumsum(140 * (7.0 ** p)) / SR) * 0.35
    out = (_sweep(d, 300, 7000, rng) + tone) * p ** 2.2
    out[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    return out


def sfx_pop(rng):
    t = _t(0.1)
    return np.sin(2 * np.pi * np.cumsum(520 * np.exp(-t * 14)) / SR) * np.exp(-t * 38)


def sfx_ding(rng):
    t = _t(1.0)
    return (np.sin(2 * np.pi * 1318.5 * t) + 0.45 * np.sin(2 * np.pi * 2637 * t)
            + 0.2 * np.sin(2 * np.pi * 3955 * t)) * np.exp(-t * 5.5) * (1 - np.exp(-t * 900))


def sfx_buzz(rng):
    """Wrong-answer buzzer (good for REJECTED / fail moments)."""
    t = _t(0.55)
    w = np.sign(np.sin(2 * np.pi * 110 * t)) * 0.6 + np.sign(np.sin(2 * np.pi * 146 * t)) * 0.4
    env = np.minimum(1, t * 200) * np.minimum(1, (0.55 - t) * 60)
    return _band(w, 60, 2500) * env


SYNTH = {"boom": sfx_boom, "hit": sfx_hit, "whoosh": sfx_whoosh, "riser": sfx_riser,
         "pop": sfx_pop, "ding": sfx_ding, "buzz": sfx_buzz}


def synth(name):
    x = SYNTH[name](np.random.default_rng(sum(map(ord, name))))
    x = x / (np.abs(x).max() + 1e-9) * 0.85
    return np.stack([x, x], axis=1).astype(np.float32)


# ----------------------------------------------------------------------- mix

def _place(bus, x, at, gain=1.0):
    i = int(round(at * SR))
    if i >= len(bus) or i + len(x) <= 0:
        return
    a, b = max(0, i), min(len(bus), i + len(x))
    bus[a:b] += x[a - i:b - i] * gain


def _atempo(speed):
    parts = []
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    parts.append(f"atempo={speed:.6f}")
    return ",".join(parts)


def _fit(x, n):
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x), 2), np.float32)])


def _edges(x, ms=6):
    k = min(len(x) // 2, int(SR * ms / 1000))
    if k > 1:
        r = np.linspace(0, 1, k)[:, None]
        x[:k] *= r
        x[-k:] *= r[::-1]
    return x


def measure_lufs(wav):
    err = run_err([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", wav, "-af", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def build_mix(plan, out_wav):
    """Game audio + music (ducked under voices) + voices + effects -> mastered wav.
    Returns a short report dict."""
    A = plan["style"]["audio"]
    N = int(round(plan["T"] * SR))
    bed = np.zeros((N, 2), np.float32)
    for s in plan["segs"]:
        clip = plan["clips"][s["clip"]]
        n = int(round(s["content"] * SR))
        if s["mute"] or not clip["info"]["has_audio"]:
            continue
        x = read_audio(clip["path"], ss=s["in"], t=s["out"] - s["in"],
                       af=None if s["speed"] == 1 else _atempo(s["speed"]))
        x = _edges(_fit(x, n))
        _place(bed, x, s["t0"], db2lin(A["bed_db"] + s["gain"]))
    if plan["music"]:
        m = read_audio(plan["music"]["path"], ss=plan["music"]["start"], t=plan["T"] + 1)
        if len(m):
            reps = int(np.ceil(N / len(m)))
            m = _fit(np.tile(m, (reps, 1)), N)
            k = min(N, int(1.2 * SR))
            m[-k:] *= np.linspace(1, 0, k)[:, None]
            bed += m * db2lin(A["music_db"] + plan["music"]["gain"])

    voice = np.zeros((N, 2), np.float32)
    active = np.zeros(N // FRAME + 2, np.float32)
    for v in plan["voices"]:
        an = analyze_voice(v["path"])
        g = min(db2lin(24), db2lin(A["voice_db"]) / max(an["rms"], 1e-4)) * db2lin(v["gain"])
        _place(voice, an["x"], v["at"], g)
        a = max(0, int((v["at"] - 0.06) * 100))
        b = min(len(active), int((v["at"] + v["dur"] + 0.12) * 100))
        active[a:b] = 1.0
    if plan["voices"]:                         # duck everything else under speech
        k = np.hanning(31)
        env = np.convolve(active, k / k.sum(), mode="same")
        gain_db = A["duck_db"] * np.clip(env, 0, 1)
        g = np.interp(np.arange(N) / FRAME, np.arange(len(gain_db)), gain_db)
        bed *= (10.0 ** (g / 20.0))[:, None].astype(np.float32)

    fxbus = np.zeros((N, 2), np.float32)
    for s in plan["sfx"]:
        x = synth(s["name"]) if "name" in s else read_audio(s["path"])
        _place(fxbus, _edges(x.copy(), 3), s["at"], db2lin(A["sfx_db"] + s["gain"]))
    if plan["cta"] and plan["cta"]["has_audio"]:
        x = read_audio(plan["cta"]["path"], t=plan["cta"]["dur"])
        _place(fxbus, _edges(x, 3), plan["cta"]["at"], db2lin(plan["style"]["cta"]["audio_db"]))

    mix = bed + voice + fxbus
    peak = float(np.abs(mix).max()) if N else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak
    raw = str(out_wav) + ".raw.wav"
    write_wav(raw, mix)
    lufs = measure_lufs(raw)
    gain = 0.0
    if lufs is not None and lufs > -60:
        gain = float(np.clip(A["master_lufs"] - lufs, -20, 20))
    ffmpeg("-i", raw, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.87:attack=3:release=60:level=0",
           "-ar", str(SR), "-c:a", "pcm_s16le", out_wav)
    return {"lufs_in": lufs, "gain_db": round(gain, 2), "lufs_out": measure_lufs(out_wav)}
