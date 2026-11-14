# Shorts Maker (FROVIXA)

Ek folder (gameplay clip + voice mp3s) se poora YouTube Short aur thumbnail banata hai,
channel ke fixed style mein. CapCut ka kaam (cuts, voice lagana, captions, effects,
export) ab ek chhoti si `short.json` file se hota hai.

**Yeh program yahan rehta hai:** `E:\Game Recordings\shorts\shorts-maker\`

| File                | Kaam                                                                                                                                             |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sm.py`             | Program ka darwaza (saari commands)                                                                                                              |
| `smlib/`            | Asal code: `spec.py` (short.json samajhna), `captions.py` (caption pills), `audio.py` (voice + mix), `video.py` (render), `thumb.py` (thumbnail) |
| `style.json`        | **House style**: font, caption size/jagah, har character ka rang, audio levels, quality. Yahan badlo to har naye Short par lagu hoga             |
| `fonts/`            | Montserrat + colour emoji font (dono free/OFL)                                                                                                   |
| `RENDER_8K_GPU.bat` | Short ka folder is par drag karo: aapke PC ke GPU se 8K final + thumbnail                                                                        |
| `SETUP_CHECK.bat`   | Ek dafa chalao: Python packages, ffmpeg aur GPU check                                                                                            |

## Har Short ka folder

```
shorts\<short_ka_naam>\
   raw clip(s).mp4            <- CapCut ka rough cut ya seedhi recording
   audio\*.mp3                <- voice lines (file ke naam se character aur text pehchana jata hai)
   sound_effect\*.mp3         <- (optional) apne sound effects / music
   short.json                 <- edit ki recipe (Claude likhta hai)
   <Name>_FINAL_8K.mp4        <- output
   <Name>_thumbnail.jpg       <- output
   <Name>_captions.srt        <- output (YouTube CC ke liye)
   _sm\                       <- kaam ki files (proxy, preview, chunks). Delete kar sakte ho
```

## Claude se kaam lena

Chat mein bas itna likho (folder connected hona chahiye):

> `trevor_bulldozer` folder ka Short bana do. Story: Michael ko parking nahi mil rahi,
> Trevor bulldozer le aata hai. Hook: "Michael trusted Trevor… 💀". Thumbnail title: "FREE PARKING?!"

Claude yeh 5 steps chalata hai (har step ek command):

1. `python3 sm.py scan <folder>` - clips, voice lines aur ek contact sheet (har 0.5s ka frame)
2. `short.json` likhta hai (neeche format)
3. `python3 sm.py preview <folder>` - 540p preview + ek review sheet (har caption ka frame)
4. `python3 sm.py render <folder>` - final (default 8K; `--res 4k` tez hai). Agar `STATUS: PARTIAL` aaye to wahi command dobara
5. `python3 sm.py thumb <folder>` - thumbnail

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

**timeline** - final video ke tukre, order mein: `[clip, in, out, {options}]` (seconds, source clip ke).
Options: `speed` (0.5 = slow-mo), `zoom` (`1.1` ya `[1.0, 1.1]` push-in), `focus` `[x, y]` 0-1 (zoom kis taraf),
`look` (`drama` `dark` `punch` `warm` `bw`), `hold` (aakhri frame itne second roko), `gain` (dB), `mute`.
Timeline na ho to poora pehla clip.

**lines** - voice lines. `audio` = scan ki list ka number ya file ke naam ka koi unique hissa.
`at` = final video mein kab shuru ho; na do to pichhli line ke `gap` (default 0.3s) baad.
`text` = caption: `|` naya caption (agla tukra), `/` nayi line. Lamba text khud tukron mein bat jata hai aur
tukre voice ke pauses par badalte hain. Zarurat ho to `cuts: [0.9, 2.7]` se tukron ka time khud do (line ke
shuru se seconds). Aur: `gain`, `hold`, `pos` (`top` `mid` `low` ya 0-1).

**hook** - shuru ka caption (bina voice): `"hook": "Wait for it… 👀"`.
**captions** - bina voice ke caption: `{"text", "who", "at", "end", "pos"}`.
**sfx** - `name`: `boom hit whoosh riser pop ding buzz` (program khud banata hai) ya `file` (apni mp3).
**fx** - `flash` ya `shake` kisi time par. **music** - `{"file": "...", "gain": -4}` (voice ke neeche khud dheema).
**cta** (optional, sirf jab aap kaho) - `files\Frovixa_LikeSubscribe_TRANSPARENT.mov` ko us time par chalata hai (`{"at": 8, "y": 0.5}`; `y` se neeche khiskao agar caption se takraye).
**clips** - 16:9 clip ho to `{"a": {"file": "x.mp4", "fit": "blur"}}` (ya `"crop"` + `"cx": 0.4`).
**thumbnail** - `t` (clip ka second), `title` (line 1 safed, line 2 peeli), `zoom`, `focus`, `sticker`, `flip`.
**style** - sirf is Short ke liye style.json ki koi cheez badalni ho.

Caption ka rang `who` se aata hai (`style.json` -> `speakers`): trevor peela, michael grey, franklin hara,
npc/cop neela. Naya character: `speakers` mein ek line add karo.

## Quality

`--res 1080 | 1440 | 4k | 8k` (default `style.json` -> `video.res`).

- Claude ke sandbox mein (GPU nahi, 2 core): 18 second ka Short 4K mein ~2 minute, 8K mein ~5-6 minute.
- **Sab se tez 8K:** `RENDER_8K_GPU.bat` - aapke PC ka NVIDIA GPU (hevc_nvenc) use karta hai.
  Pehli dafa `SETUP_CHECK.bat` chalao (Python + `winget install Gyan.FFmpeg`).

Render tukron (chunks) mein hota hai: beech mein ruk jaye to wahi command dobara chalao, wahin se aage chalega.
Sirf ek caption badlo to sirf wahi tukra dobara render hota hai.

Jagah khali karni ho: `python3 sm.py clean <folder>` (render ke cached tukre hata deta hai, final video rehti hai),
ya `_sm` folder khud delete kar do.
