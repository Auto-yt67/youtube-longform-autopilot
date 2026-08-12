# Car Professor - Automated Video Pipeline

Fully automated pipeline: picks a topic, writes a script, sources images,
generates a voiceover, builds the video, and uploads it to YouTube - on a
schedule, with no manual work per video.

**Cost: $0.** Everything used is free (Groq's free API tier, Wikimedia
Commons, Piper open-source TTS, GitHub Actions' free minutes for public
repos).

## Pipeline stages

| # | Stage | File | What it does |
|---|-------|------|---------------|
| 1 | Topic | `src/topic_generator.py` | Picks a new catalog-format topic, avoids repeats |
| 2 | Script | `src/script_writer.py` | Writes the segment-by-segment narration |
| 3 | Images | `src/image_fetcher.py` | Pulls license-clear images per segment from Wikimedia Commons |
| 4 | Voiceover | `src/tts_engine.py` | Narrates the script with free offline Piper TTS |
| 5 | Video | `src/video_builder.py` | Assembles zoom-in/cutaway/zoom-out pacing per segment |
| 5b | Thumbnail | `src/thumbnail_generator.py` | Builds the grid-of-circles thumbnail |
| 6 | Upload | `src/youtube_upload.py` | Publishes to YouTube with title/description/tags/thumbnail |

`src/pipeline.py` runs all six stages in order.

## Setup

If you're reusing credentials from a previous build, you likely already have
these repository secrets set (**Settings > Secrets and variables > Actions**):

- `GROQ_API_KEY` - free key from [console.groq.com](https://console.groq.com), powers topic + script generation
- `YOUTUBE_CLIENT_SECRETS` - your YouTube Data API OAuth client (raw JSON or base64, either works)
- `YOUTUBE_TOKEN_PICKLE_B64` - your cached, already-approved OAuth token

If so, you're done - no browser login needed, since the token was already
approved in a prior run. Google refresh tokens don't expire unless revoked,
so old credentials keep working indefinitely.

You can drop any leftover secret from the old image-generation build (e.g. an
image-gen API key) - this pipeline doesn't use one, since images now come
free from Wikimedia Commons.

### Starting from scratch instead
1. Sign up at [console.groq.com](https://console.groq.com) for a free API key
2. In [Google Cloud Console](https://console.cloud.google.com), create a
   project, enable the **YouTube Data API v3**, and create OAuth 2.0
   credentials (Desktop app type) - download as `client_secrets.json`
3. Run the one-time interactive login locally (needs a human to click
   "Allow" once - this is the only part that can't be automated):
   ```bash
   cd src
   export YOUTUBE_CLIENT_SECRETS=../client_secrets.json
   python youtube_upload.py --auth-only
   ```
4. Encode and store both as GitHub secrets:
   ```bash
   base64 -w0 client_secrets.json   # -> YOUTUBE_CLIENT_SECRETS
   base64 -w0 token.pickle          # -> YOUTUBE_TOKEN_PICKLE_B64
   ```
5. Delete the local files afterward - don't commit them to the repo.

### Done either way
The workflow in `.github/workflows/publish.yml` runs Mon/Wed/Fri at 3pm UTC
by default (edit the cron line to change frequency). You can also trigger a
run manually from the **Actions** tab any time.

## Notes / things worth knowing

- **Images are Wikimedia Commons only**, filtered to public domain / CC0 /
  CC-BY / CC-BY-SA licenses. This is what keeps the channel monetization-safe
  - no scraped stock photos or news images that could trigger a copyright claim.
- **Piper TTS** is CPU-only and free forever. Quality is decent, not
  ElevenLabs-tier, but a big step up from classic robotic TTS. Swap `VOICE` in
  `tts_engine.py` for other free Piper voices if you want a different sound.
- **No background music** in this first version, since royalty-free music
  sourcing has its own licensing gotchas. Easy to add later via the YouTube
  Audio Library if you want to download tracks manually and drop them in
  `assets/music/`.
- If a segment's image search comes back empty (rare, but happens for very
  obscure topics), that segment is silently dropped rather than shipping a
  blank frame - check the run artifact's `script.json` if a video looks short.
- Runtime for a 12-item video: roughly 8-12 minutes on a GitHub-hosted runner.
