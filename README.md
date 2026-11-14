# Shorts Maker

A small Python + ffmpeg engine that edits YouTube Shorts from a recipe file instead of a timeline editor.

Put a raw clip and voice-line mp3s in a folder, describe the edit in `short.json` (cuts, who says what, captions, effects), and run:

    python sm.py scan    <folder>   # list clips and voice lines, build a contact sheet, draft short.json
    python sm.py preview <folder>   # fast 540p preview + review sheet
    python sm.py render  <folder>   # final video, 1080p to 8K, resumable
    python sm.py thumb   <folder>   # matching thumbnail

Features
- Caption pills coloured per speaker, with colour emoji, timed to the pauses in each voice line
- Cuts, slow-mo, zoom, looks, flash and shake
- Voice normalisation, game-audio ducking, built-in sound effects, -14 LUFS master
- Chunked rendering: stops and resumes, and re-renders only what changed
- NVIDIA GPU (hevc_nvenc) when available, x264 otherwise
- One `style.json` for the channel's fonts, colours, caption position and quality

Requirements: Python 3.10+, `pip install pillow numpy`, ffmpeg on PATH.

Fonts: Montserrat and Noto Color Emoji, both under the SIL Open Font License 1.1.
