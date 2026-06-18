"""
Voiceover generation using Kokoro TTS (free, open source)
Generates a natural-sounding voiceover WAV file from narration text
"""

import subprocess
import sys
import os


def ensure_kokoro():
    """Install kokoro if not present."""
    try:
        import kokoro
        return True
    except ImportError:
        print("  Installing Kokoro TTS...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "kokoro>=0.9.4", "soundfile", "-q"])
        return True


def generate_voiceover(narration: str, output_path: str, voice: str = "af_heart", speed: float = 1.0):
    """
    Generate voiceover audio from narration text using Kokoro TTS.
    
    Args:
        narration: Full narration text
        output_path: Path to save the WAV file
        voice: Kokoro voice ID. Good options:
               'af_heart' (American female, warm)
               'am_echo'  (American male)
               'bf_emma'  (British female)
        speed: Speaking speed (0.5 - 2.0, default 1.0)
    """
    ensure_kokoro()

    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    print(f"  Loading Kokoro TTS with voice '{voice}'...")
    pipeline = KPipeline(lang_code="a")  # 'a' = American English

    # Kokoro handles long text by chunking internally
    print(f"  Synthesizing {len(narration)} characters of narration...")
    
    audio_chunks = []
    # Add a brief silence between chunks for natural pacing
    silence_samples = int(0.3 * 24000)  # 0.3s silence at 24kHz
    silence = np.zeros(silence_samples, dtype=np.float32)

    generator = pipeline(narration, voice=voice, speed=speed, split_pattern=r"(?<=[.!?])\s+")
    
    for i, (gs, ps, audio) in enumerate(generator):
        audio_chunks.append(audio)
        audio_chunks.append(silence)

    if not audio_chunks:
        raise RuntimeError("Kokoro TTS produced no audio output")

    full_audio = np.concatenate(audio_chunks)
    
    sf.write(output_path, full_audio, 24000)
    duration = len(full_audio) / 24000
    print(f"  Generated {duration:.1f}s of audio")
    return output_path


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else (
        "Welcome to Car Explained. Today we're going to talk about how your car engine works. "
        "It's actually pretty simple once you break it down. Let's start from the beginning."
    )
    generate_voiceover(text, "test_voiceover.wav")
    print("Saved to test_voiceover.wav")
