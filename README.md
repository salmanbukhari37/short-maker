# Shorts Maker (FROVIXA)

Turns a folder (a gameplay clip + voice-line MP3s) into a finished YouTube Short and thumbnail,
in the channel's fixed house style. Everything you would normally do in CapCut (cuts, placing
voice lines, captions, effects, export) is driven by one small `short.json` file.

| File                | Purpose                                                                                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sm.py`             | Entry point for all commands                                                                                                                                 |
| `smlib/`            | The actual code: `spec.py` (parses short.json), `captions.py` (caption pills), `audio.py` (voices + mix), `video.py` (render), `thumb.py` (thumbnail)        |
| `style.json`        | **House style**: font, caption size/position, per-character colours, audio levels, quality. Changes here apply to every new Short                             |
| `fonts/`            | Montserrat + a colour emoji font (both free / OFL)                                                                                                           |
| `RENDER_8K_GPU.bat` | Drag a Short's folder onto this to render the 8K final + thumbnail on your PC's GPU                                                                          |
| `SETUP_CHECK.bat`   | Run once: checks Python packages, ffmpeg and the GPU encoder                                                                                                 |

## Requirements

- Python 3 with `pillow` and `numpy` (`pip install pillow numpy`)
- `ffmpeg` on your `PATH` (Windows: `winget install Gyan.FFmpeg`)
- Optional: an NVIDIA GPU for fast `hevc_nvenc` encoding

Run `python3 sm.py doctor` (or `SETUP_CHECK.bat` on Windows) to verify your setup.

## Folder layout for each Short

```
shorts\<short_name>\
   raw clip(s).mp4            <- CapCut rough cut or a straight recording
   audio\*.mp3                <- voice lines (character and text are inferred from the file name)
   sound_effect\*.mp3         <- (optional) your own sound effects / music
   short.json                 <- the edit recipe
   <Name>_FINAL_8K.mp4        <- output
   <Name>_thumbnail.jpg       <- output
   <Name>_captions.srt        <- output (for YouTube closed captions)
   _sm\                       <- working files (proxies, previews, chunks). Safe to delete
```

## Workflow

The tool was designed to be driven by an AI assistant such as Claude, but every step is a plain
command you can run yourself. A typical request looks like:

> Make a Short from the `trevor_bulldozer` folder. Story: Michael can't find parking, so
> Trevor shows up with a bulldozer. Hook: "Michael trusted Trevor… 💀". Thumbnail title: "FREE PARKING?!"

That runs these 5 steps (one command each):

1. `python3 sm.py scan <folder>` - lists clips and voice lines, and builds a contact sheet (one frame every 0.5s)
2. Write `short.json` (format below)
3. `python3 sm.py preview <folder>` - 540p preview + a review sheet (one frame per caption)
4. `python3 sm.py render <folder>` - final render (8K by default; `--res 4k` is faster). If it prints `STATUS: PARTIAL`, run the same command again
5. `python3 sm.py thumb <folder>` - thumbnail

Other commands:

- `python3 sm.py frames <folder> <clip> <t0> <t1> [--n 10]` - grab frames from a clip between two timestamps
- `python3 sm.py clean <folder>` - remove cached render chunks
- `python3 sm.py doctor` - check Python packages, ffmpeg and GPU encoder

## short.json

```json
{
  "name": "Trevor_Proposal",
  "clips": { "a": "raw.mp4" },
  "timeline": [
    ["a", 0, 12.4],
    ["a", 12.4, 14.0, { "speed": 0.5, "look": "drama" }],
    ["a", 14.0, 17.0, { "zoom": [1.0, 1.08], "hold": 0.5 }]
  ],
  "lines": [
    {
      "who": "trevor",
      "audio": 8,
      "at": 0.2,
      "text": "Trevor wants to marry your daughter 💀"
    },
    {
      "who": "michael",
      "audio": 2,
      "at": 3.0,
      "text": "So… | what do you do / for a living?"
    },
    { "who": "trevor", "audio": 3, "text": "I run my own business, / sir.💀" },
    { "who": "michael", "audio": "Rejected", "text": "REJECTED ❌" }
  ],
  "sfx": [{ "at": 12.4, "name": "boom" }],
  "fx": [
    { "at": 12.4, "type": "flash" },
    { "at": 12.4, "type": "shake", "dur": 0.6 }
  ],
  "thumbnail": {
    "clip": "a",
    "t": 12.9,
    "title": ["MARRY MY", "DAUGHTER?"],
    "sticker": { "text": "REJECTED!", "at": [0.7, 0.56] }
  }
}
```

**timeline** - the pieces of the final video, in order: `[clip, in, out, {options}]` (seconds in the source clip).
Options: `speed` (0.5 = slow-mo), `zoom` (`1.1` or `[1.0, 1.1]` for a push-in), `focus` `[x, y]` 0-1 (where to zoom),
`look` (`drama` `dark` `punch` `warm` `bw`), `hold` (freeze the last frame for this many seconds), `gain` (dB), `mute`.
If there is no timeline, the whole first clip is used.

**lines** - voice lines. `audio` = the number from the scan list, or any unique part of the file name.
`at` = when it starts in the final video; if omitted, it starts `gap` seconds (default 0.3s) after the previous line.
`text` = the caption: `|` starts a new caption (next chunk), `/` starts a new line. Long text is split into chunks
automatically, and chunks switch on the pauses in the voice. If needed, set chunk timings yourself with
`cuts: [0.9, 2.7]` (seconds from the start of the line). Also: `gain`, `hold`, `pos` (`top` `mid` `low` or 0-1).

**hook** - an opening caption with no voice: `"hook": "Wait for it… 👀"`.
**captions** - captions with no voice: `{"text", "who", "at", "end", "pos"}`.
**sfx** - `name`: `boom hit whoosh riser pop ding buzz` (generated by the program) or `file` (your own MP3).
**fx** - `flash` or `shake` at a given time. **music** - `{"file": "...", "gain": -4}` (automatically ducked under voices).
**cta** (optional, only when asked for) - plays `files\Frovixa_LikeSubscribe_TRANSPARENT.mov` at the given time (`{"at": 8, "y": 0.5}`; increase `y` to move it down if it overlaps a caption).
**clips** - for a 16:9 clip use `{"a": {"file": "x.mp4", "fit": "blur"}}` (or `"crop"` + `"cx": 0.4`).
**thumbnail** - `t` (second in the clip), `title` (line 1 white, line 2 yellow), `zoom`, `focus`, `sticker`, `flip`.
**style** - override anything from style.json for this Short only.

Caption colour comes from `who` (`style.json` -> `speakers`): trevor yellow, michael grey, franklin green,
npc/cop blue. To add a new character, add one line to `speakers`.

## Quality

`--res 1080 | 1440 | 4k | 8k` (default: `style.json` -> `video.res`). `--codec auto | nvenc | x264 | x265`.

- CPU only (2 cores, no GPU): an 18-second Short takes ~2 minutes at 4K and ~5-6 minutes at 8K.
- **Fastest 8K:** `RENDER_8K_GPU.bat` uses your PC's NVIDIA GPU (`hevc_nvenc`).
  Run `SETUP_CHECK.bat` first (Python + `winget install Gyan.FFmpeg`).

Rendering happens in chunks: if it stops midway, run the same command again and it resumes where it left off.
If you change only one caption, only that chunk is re-rendered.

To free up disk space: `python3 sm.py clean <folder>` (removes cached render chunks; the final video is kept),
or just delete the `_sm` folder.
