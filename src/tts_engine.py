"""
Stage 4: Text-to-speech.

Narrator chain (each falls back to the next if it fails, so a run never dies
on TTS):
  1. Speechma (Andrew voice, +7% rate) - free online neural voice, most natural
  2. Edge-TTS (Eric) - free online neural fallback
  3. Piper (Bryce) - fully offline, always-works last resort

Speechma is an UNOFFICIAL endpoint (no official API), so it may break without
notice or be gated by a captcha that blocks automated requests. The fallback
chain means if that happens in CI, the pipeline drops to Edge-TTS (and then
Piper) and still produces a video rather than failing. Watch the run logs: if
you see "Speechma failed - falling back", that's the captcha/endpoint issue and
the video will use the Edge (Eric) voice instead.

All engines output WAV so the rest of the pipeline (which reads WAV durations
for audio-driven video timing) is unchanged. Speechma/Edge return MP3, which we
convert to WAV with ffmpeg (already installed in the workflow).
"""

import asyncio
import subprocess
import wave
from pathlib import Path

import requests

# --- Speechma (primary) ---
SPEECHMA_URL = "https://speechma.com/com.api/tts-api.php"
SPEECHMA_VOICE = "voice-108"   # Andrew (English, US, male)
SPEECHMA_RATE = 7              # +7% speed
SPEECHMA_PITCH = 0
SPEECHMA_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.6778.140 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://speechma.com",
    "Referer": "https://speechma.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

# --- Edge-TTS (fallback 1) ---
EDGE_VOICE = "en-US-EricNeural"
EDGE_RATE = "+25%"

# --- Piper (fallback 2) ---
PIPER_VOICE = "en_US-bryce-medium"
PIPER_VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"
PIPER_MODEL_PATH = PIPER_VOICE_DIR / f"{PIPER_VOICE}.onnx"


def _speechma_to_mp3(text: str, mp3_path: Path):
    """Synthesize via Speechma's (unofficial) endpoint. Raises on any failure."""
    # Speechma strips quotes and converts & -> and; do the same so what we send
    # matches what the site would send, and keep our pause characters (,;!) intact.
    clean = text.replace("'", "").replace('"', "").replace("&", "and")
    payload = {
        "text": clean,
        "voice": SPEECHMA_VOICE,
        "rate": SPEECHMA_RATE,
        "pitch": SPEECHMA_PITCH,
    }
    resp = requests.post(SPEECHMA_URL, json=payload, headers=SPEECHMA_HEADERS, timeout=60)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "audio" not in ctype:
        # not audio -> almost certainly a captcha/HTML page, treat as failure
        raise RuntimeError(f"Speechma returned non-audio ({ctype or 'unknown'})")
    if not resp.content or len(resp.content) < 1000:
        raise RuntimeError("Speechma returned empty/too-small audio")
    mp3_path.write_bytes(resp.content)


def _edge_to_mp3(text: str, mp3_path: Path):
    """Synthesize text to mp3 via Edge-TTS. Raises on any failure."""
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
        await communicate.save(str(mp3_path))

    asyncio.run(_run())
    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise RuntimeError("Edge-TTS produced no audio")


def _mp3_to_wav(mp3_path: Path, wav_path: Path):
    """Convert mp3 -> wav with ffmpeg (present in the CI workflow)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), str(wav_path)],
        check=True, capture_output=True,
    )


def _piper_to_wav(text: str, wav_path: Path):
    """Fallback synth via offline Piper."""
    model_arg = str(PIPER_MODEL_PATH) if PIPER_MODEL_PATH.exists() else PIPER_VOICE
    subprocess.run(
        ["piper", "--model", model_arg, "--output_file", str(wav_path)],
        input=text.encode("utf-8"),
        check=True,
    )


def synthesize(text: str, out_path: Path):
    """
    Synthesize text to a WAV file. Tries Speechma (Andrew, +7%) first, then
    Edge-TTS (Eric), then Piper - so the run never dies on TTS.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_tmp = out_path.with_suffix(".mp3")

    # 1) Speechma
    try:
        _speechma_to_mp3(text, mp3_tmp)
        _mp3_to_wav(mp3_tmp, out_path)
        return
    except Exception as e:
        print(f"  ! Speechma failed ({e}) - falling back to Edge-TTS")
    finally:
        if mp3_tmp.exists():
            try:
                mp3_tmp.unlink()
            except OSError:
                pass

    # 2) Edge-TTS
    try:
        _edge_to_mp3(text, mp3_tmp)
        _mp3_to_wav(mp3_tmp, out_path)
        return
    except Exception as e:
        print(f"  ! Edge-TTS failed ({e}) - falling back to Piper")
    finally:
        if mp3_tmp.exists():
            try:
                mp3_tmp.unlink()
            except OSError:
                pass

    # 3) Piper (offline, always works)
    _piper_to_wav(text, out_path)


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)


def synthesize_segments(segments: list, intro: str, outro: str, out_dir: Path) -> list:
    """
    Synthesize the intro, each segment's script, and the outro to individual
    wav files. Returns list of dicts: {name, wav_path, duration}, with the
    intro first and outro last.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    intro_path = out_dir / "intro.wav"
    synthesize(intro, intro_path)
    results.append({
        "name": "intro",
        "wav_path": str(intro_path),
        "duration": get_wav_duration(intro_path),
    })

    for i, seg in enumerate(segments):
        wav_path = out_dir / f"segment_{i:02d}.wav"
        synthesize(seg["script"], wav_path)
        results.append({
            "name": seg["name"],
            "wav_path": str(wav_path),
            "duration": get_wav_duration(wav_path),
        })

    outro_path = out_dir / "outro.wav"
    synthesize(outro, outro_path)
    results.append({
        "name": "outro",
        "wav_path": str(outro_path),
        "duration": get_wav_duration(outro_path),
    })

    return results


if __name__ == "__main__":
    test_out = Path("/tmp/tts_test.wav")
    synthesize("This is a test of the Car Professor voiceover pipeline.", test_out)
    print(f"Wrote {test_out}, duration: {get_wav_duration(test_out):.2f}s")
