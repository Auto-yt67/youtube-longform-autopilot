"""
Scene-to-audio timestamp alignment using faster-whisper
Transcribes the audio with word-level timestamps, then maps each scene's
narration excerpt to its start/end time in the audio.
"""

import subprocess
import sys
import re
from difflib import SequenceMatcher


def ensure_faster_whisper():
    try:
        import faster_whisper
    except ImportError:
        print("  Installing faster-whisper...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "faster-whisper", "-q"])


def normalize(text: str) -> str:
    """Normalize text for comparison — lowercase, strip punctuation."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def find_best_match_window(words: list, query_words: list) -> tuple[float, float]:
    """
    Find the start/end timestamps in `words` (list of word dicts with start/end)
    that best match `query_words` using sliding window + fuzzy match.
    """
    query_norm = [normalize(w) for w in query_words]
    query_len = len(query_norm)
    best_score = 0
    best_start = words[0]["start"]
    best_end = words[min(query_len, len(words) - 1)]["end"]

    for i in range(max(1, len(words) - query_len + 1)):
        window = words[i:i + query_len]
        window_norm = [normalize(w["word"]) for w in window]
        score = SequenceMatcher(None, query_norm, window_norm).ratio()
        if score > best_score:
            best_score = score
            best_start = window[0]["start"]
            best_end = window[-1]["end"]

    return best_start, best_end


def align_scenes_to_audio(audio_path: str, scenes: list) -> list:
    """
    Align scenes to audio timestamps using Whisper transcription.
    
    Returns list of scene timing dicts:
    [{"id": 1, "start": 0.0, "end": 5.2, "image_prompt": "..."}, ...]
    """
    ensure_faster_whisper()
    from faster_whisper import WhisperModel

    print("  Loading Whisper model (base.en)...")
    model = WhisperModel("base.en", device="cpu", compute_type="int8")

    print("  Transcribing audio with word timestamps...")
    segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
    )

    # Flatten all words
    all_words = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                all_words.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })

    total_duration = all_words[-1]["end"] if all_words else 10.0
    print(f"  Transcribed {len(all_words)} words, {total_duration:.1f}s total")

    # Align each scene
    scene_timings = []
    for scene in scenes:
        excerpt = scene.get("narration_excerpt", "")
        excerpt_words = excerpt.split()

        if len(excerpt_words) < 2 or not all_words:
            # Fallback: evenly distribute
            idx = scene["id"] - 1
            start = idx * (total_duration / len(scenes))
            end = (idx + 1) * (total_duration / len(scenes))
        else:
            start, end = find_best_match_window(all_words, excerpt_words)

        scene_timings.append({
            "id": scene["id"],
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "image_prompt": scene.get("image_prompt", ""),
            "narration_excerpt": excerpt,
        })

    # Ensure no overlap and fill gaps — each image shows until next scene starts
    for i in range(len(scene_timings) - 1):
        scene_timings[i]["end"] = scene_timings[i + 1]["start"]
        scene_timings[i]["duration"] = round(
            scene_timings[i]["end"] - scene_timings[i]["start"], 3
        )

    # Last scene ends at total duration
    scene_timings[-1]["end"] = round(total_duration, 3)
    scene_timings[-1]["duration"] = round(
        total_duration - scene_timings[-1]["start"], 3
    )

    return scene_timings


if __name__ == "__main__":
    import json, sys
    audio = sys.argv[1]
    scenes_file = sys.argv[2]
    with open(scenes_file) as f:
        data = json.load(f)
    timings = align_scenes_to_audio(audio, data["scenes"])
    print(json.dumps(timings, indent=2))
