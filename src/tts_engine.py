"""
Stage 4: Text-to-speech.

Primary narrator: Edge-TTS (Microsoft Edge's online neural voices) - free, no
API key, no account, much more natural than Piper. Voice: Eric at 1.5x speed.

Fallback: Piper (fully offline, open-source). If an Edge-TTS call fails for any
reason - network blip, Microsoft changing the endpoint, etc. - that segment
falls back to Piper so the pipeline always completes rather than crashing.

Both output WAV so the rest of the pipeline (which reads WAV durations for
audio-driven video timing) is unchanged. Edge-TTS returns MP3, which we convert
to WAV with ffmpeg (already installed in the workflow for video assembly).
"""

import asyncio
import subprocess
import wave
from pathlib import Path

# --- Edge-TTS (primary) ---
EDGE_VOICE = "en-US-EricNeural"   # chosen narrator
EDGE_RATE = "+50%"                # 1.5x speed

# --- Piper (fallback) ---
PIPER_VOICE = "en_US-bryce-medium"
PIPER_VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"
PIPER_MODEL_PATH = PIPER_VOICE_DIR / f"{PIPER_VOICE}.onnx"


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
    Synthesize text to a WAV file. Tries Edge-TTS (Eric, 1.5x) first; if that
    fails for any reason, falls back to Piper so the run never dies on TTS.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_tmp = out_path.with_suffix(".mp3")
    try:
        _edge_to_mp3(text, mp3_tmp)
        _mp3_to_wav(mp3_tmp, out_path)
    except Exception as e:
        print(f"  ! Edge-TTS failed ({e}) - falling back to Piper for this segment")
        _piper_to_wav(text, out_path)
    finally:
        if mp3_tmp.exists():
            try:
                mp3_tmp.unlink()
            except OSError:
                pass


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
