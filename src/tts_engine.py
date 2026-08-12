"""
Stage 4: Text-to-speech.
Uses Piper (https://github.com/rhasspy/piper) - fully free, open-source,
runs offline/locally (no API, no per-character cost), and sounds
significantly better than classic robotic TTS like espeak. CPU-only,
fast enough for CI runners.

Setup (handled in the GitHub Actions workflow, or run manually):
    pip install piper-tts
    # downloads a voice model on first use, or pre-fetch with:
    python -m piper.download_voices en_US-norman-medium
"""

import subprocess
import wave
from pathlib import Path

VOICE = "en_US-norman-medium"  # male narration voice

# Playback speed. Piper's length_scale is INVERSE to speed:
#   1.0  = normal
#   0.80 = 1.25x faster  <-- current setting
#   0.67 = 1.5x faster
LENGTH_SCALE = 0.80

# Must match the --download-dir used in the GitHub Actions workflow's
# "Download Piper voice model" step. Using a fixed absolute path (rather than
# relying on the current working directory) means TTS works the same whether
# it's invoked from src/, the repo root, or anywhere else.
VOICE_DIR = Path.home() / ".local" / "share" / "piper-voices"
VOICE_MODEL_PATH = VOICE_DIR / f"{VOICE}.onnx"


def synthesize(text: str, out_path: Path):
    """Synthesize a block of text to a wav file using Piper."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model_arg = str(VOICE_MODEL_PATH) if VOICE_MODEL_PATH.exists() else VOICE
    subprocess.run(
        [
            "piper",
            "--model", model_arg,
            "--length_scale", str(LENGTH_SCALE),
            "--output_file", str(out_path),
        ],
        input=text.encode("utf-8"),
        check=True,
    )


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)


def synthesize_segments(segments: list, outro: str, out_dir: Path) -> list:
    """
    Synthesize each segment's script (plus the outro) to individual wav files.
    Returns list of dicts: {name, wav_path, duration}
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

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
