# 🚗 Car Education YouTube Automation Pipeline

Fully automated pipeline to produce and upload car education videos with stickman animations.

**100% Free Stack:**
- **Script** → Groq (llama-3.3-70b-versatile, free tier)
- **Voiceover** → Kokoro TTS (open source, runs locally)
- **Scene Alignment** → faster-whisper (runs locally)
- **Images** → Pollinations.ai (free, no API key)
- **Video Assembly** → FFmpeg
- **Upload** → YouTube Data API v3

---

## Setup

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install -y ffmpeg python3-pip
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file (or export to your shell):

```bash
export GROQ_API_KEY=your_groq_api_key_here
```

Get a free Groq API key at https://console.groq.com

### 3. Set up YouTube API (one-time)

1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable **YouTube Data API v3**
4. Go to **Credentials** → Create **OAuth 2.0 Client ID** → Desktop App
5. Download the JSON and save as `client_secrets.json` in this directory
6. First run will open a browser for OAuth consent — after that, token is cached

---

## Usage

### Generate a single video

```bash
python pipeline.py "How does a car engine work?"
```

Output goes to `./output/` by default.

### Specify output directory

```bash
python pipeline.py "The History of Ferrari" --output ./ferrari_video
```

### Skip upload (local render only)

```bash
python pipeline.py "Why do cars have catalytic converters?" --no-upload
```

### Generate topic ideas

```bash
python generate_topics.py
```
Saves 20 viral topic ideas to `topic_ideas.json`.

---

## Pipeline Steps

```
Topic
  │
  ▼
[1] Script Generation (Groq)
    → title, description, tags
    → full narration text
    → 12-18 scenes with image prompts
    → saved to output/script.json
  │
  ▼
[2] Voiceover (Kokoro TTS)
    → natural-sounding narration audio
    → saved to output/voiceover.wav
  │
  ▼
[3] Timestamp Alignment (faster-whisper)
    → word-level transcription of voiceover
    → each scene's narration excerpt matched to timestamps
    → saved to output/timestamps.json
  │
  ▼
[4] Image Generation (Pollinations.ai)
    → one image per scene
    → stickman/diagram style
    → saved to output/images/scene_001.png ...
  │
  ▼
[5] Video Assembly (FFmpeg)
    → images shown for exact scene duration
    → crossfade transitions between scenes
    → mixed with voiceover audio
    → saved to output/final_video.mp4
  │
  ▼
[6] YouTube Upload (YouTube Data API v3)
    → uploads with title, description, tags
    → returns video URL
```

---

## Caching

Each step saves its output. If you re-run the pipeline with the same output directory, completed steps are skipped. This is useful for:
- Re-generating just the images without re-running TTS
- Re-uploading a finished video
- Debugging individual steps

To force a fresh run, delete the output directory or use a new `--output` path.

---

## Customization

### Change voice
Edit `tts.py` → `voice` parameter. Options:
- `am_michael` — American male, deep/documentary-style (default)
- `am_onyx` — American male, deep, alternate option
- `af_heart` — American female, warm
- `bf_emma` — British female

### Change image style
Edit `image_gen.py` → `STYLE_PREFIX`. The prefix is prepended to every image prompt.

### Change video length / scene count
Edit `script_gen.py` → `SYSTEM_PROMPT`. Adjust the number of scenes.

### Upload as private/unlisted
Edit `pipeline.py` or pass `privacy="private"` to `upload_to_youtube()`.

---

## Costs

| Component | Cost |
|-----------|------|
| Groq (script gen) | Free (rate limited) |
| Kokoro TTS | Free (local) |
| faster-whisper | Free (local) |
| Pollinations.ai | Free |
| FFmpeg | Free |
| YouTube Data API | Free |
| **Total** | **$0** |

---

## Troubleshooting

**Kokoro TTS slow on first run** — it downloads the model (~300MB) once and caches it.

**Pollinations.ai image failed** — retried 3x automatically; falls back to white placeholder. Re-run the pipeline (images are cached, so only failed ones retry).

**YouTube auth popup not showing** — run from a machine with a browser, or use `--no-upload` on the server and upload manually.

**faster-whisper first run slow** — downloads `base.en` model (~150MB) once.
