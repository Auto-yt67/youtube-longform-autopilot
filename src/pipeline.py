"""
Full pipeline orchestrator. Runs every stage end to end:
  topic -> script -> images -> intro -> voiceover -> video -> thumbnail -> upload

Run this from GitHub Actions on a schedule, or locally with:
    python src/pipeline.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from topic_generator import generate_topic, save_used_topic
from script_writer import (
    generate_script, generate_additional_segments, generate_intro, pick_accent_word
)
from image_fetcher import download_images
from tts_engine import synthesize_segments, synthesize, get_wav_duration
from video_builder import build_video
from thumbnail_generator import build_thumbnail
from youtube_upload import upload_to_youtube

WORKDIR = Path("run_output") / datetime.now().strftime("%Y%m%d_%H%M%S")

# Piper's approximate narration speed for this voice. Used only to estimate
# runtime from word count before TTS runs (TTS is the slow step, so we top
# up the script BEFORE synthesizing rather than after).
#
# NOTE: this must track tts_engine.LENGTH_SCALE. At length_scale 0.80 (1.25x)
# the effective rate is ~175 wpm, not the ~140 wpm of the old 1.0x voice.
# Leaving this at 140 would make every video overshoot the target by ~25%.
WORDS_PER_MINUTE = 175
TARGET_MIN_SECONDS = 8 * 60 + 30  # 8.5 min - small buffer since some segments
                                   # get dropped later if no clear-license images exist
MAX_TOPUP_ROUNDS = 4
SEGMENTS_PER_TOPUP = 3


def _estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_MINUTE * 60


def _total_estimated_seconds(script: dict) -> float:
    total = sum(_estimate_seconds(s["script"]) for s in script["segments"])
    total += _estimate_seconds(script["outro"])
    return total


def run():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    print(f"== Working directory: {WORKDIR} ==")

    # 1. Topic
    print("\n[1/6] Generating topic...")
    topic = generate_topic()
    print(f"  Topic: {topic['title']}")

    # 2. Script
    print("\n[2/6] Writing script...")
    script = generate_script(topic)
    segments = script["segments"]
    print(f"  {len(segments)} segments written")

    # Top up if the script is running short of the 8-minute target -
    # cheaper to estimate from word count now than to run TTS and redo it
    estimated = _total_estimated_seconds(script)
    print(f"  Estimated runtime: {estimated / 60:.1f} min (target: {TARGET_MIN_SECONDS / 60:.1f} min)")
    rounds = 0
    while estimated < TARGET_MIN_SECONDS and rounds < MAX_TOPUP_ROUNDS:
        rounds += 1
        print(f"  Below target - requesting {SEGMENTS_PER_TOPUP} more segments (round {rounds})...")
        existing_names = [s["name"] for s in segments]
        extra = generate_additional_segments(topic, existing_names, SEGMENTS_PER_TOPUP)
        segments.extend(extra)
        script["segments"] = segments
        estimated = _total_estimated_seconds(script)
        print(f"  New estimated runtime: {estimated / 60:.1f} min ({len(segments)} segments total)")

    (WORKDIR / "script.json").write_text(json.dumps(script, indent=2))

    # 3. Images
    print("\n[3/6] Sourcing images from Wikimedia Commons...")
    images_by_segment = {}
    representative_images = []
    for i, seg in enumerate(segments):
        out_dir = WORKDIR / "images" / f"seg_{i:02d}"
        try:
            paths = download_images(seg["image_query"], out_dir, limit=4)
        except Exception as e:
            print(f"  ! unexpected failure sourcing images for '{seg['name']}' ({e}) - treating as 0 images")
            paths = []
        if not paths:
            print(f"  ! No clear-license images found for '{seg['name']}' "
                  f"(query: {seg['image_query']}) - segment will be skipped")
        images_by_segment[i] = paths
        representative_images.append(paths[0] if paths else None)
        print(f"  {seg['name']}: {len(paths)} images")

    # Drop segments with zero usable images rather than shipping a blank frame
    usable = [i for i in range(len(segments)) if images_by_segment[i]]
    if len(usable) < len(segments):
        segments = [segments[i] for i in usable]
        images_by_segment = {new_i: images_by_segment[old_i] for new_i, old_i in enumerate(usable)}
        representative_images = [representative_images[i] for i in usable]

    # 3b. Intro - written HERE, not in stage 2, because only now is the final
    # item list known: the top-up loop above may have added segments, and
    # image sourcing may have dropped others. An intro written any earlier
    # would promise cars that never appear on screen.
    print("\n[3b/6] Writing intro narration...")
    intro_text = generate_intro(topic, [s["name"] for s in segments])
    script["intro"] = intro_text
    (WORKDIR / "script.json").write_text(json.dumps(script, indent=2))
    print(f"  Intro: {len(intro_text.split())} words")

    # 4. Voiceover
    print("\n[4/6] Generating voiceover (Piper TTS)...")
    audio_dir = WORKDIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    intro_wav = audio_dir / "intro.wav"
    synthesize(intro_text, intro_wav)
    intro_audio = {
        "name": "intro",
        "wav_path": str(intro_wav),
        "duration": get_wav_duration(intro_wav),
    }
    print(f"  Intro voiceover: {intro_audio['duration']:.1f}s")

    audio_results = synthesize_segments(segments, script["outro"], audio_dir)
    total_duration = intro_audio["duration"] + sum(a["duration"] for a in audio_results)
    print(f"  Total runtime: {total_duration / 60:.1f} min")

    # 5. Video + thumbnail
    print("\n[5/6] Assembling video...")
    video_path = WORKDIR / "final_video.mp4"
    build_video(segments, audio_results, images_by_segment, video_path,
                intro_audio=intro_audio, title=script["title"])

    thumb_path = WORKDIR / "thumbnail.png"
    accent_word = pick_accent_word(script["title"])
    print(f"  Thumbnail accent word: {accent_word}")
    build_thumbnail(
        [s["name"] for s in segments],
        representative_images,
        script["title"],
        thumb_path,
        accent_word=accent_word,
    )
    print(f"  Video: {video_path}")
    print(f"  Thumbnail: {thumb_path}")

    # 6. Upload
    print("\n[6/6] Uploading to YouTube...")
    description = (
        f"{topic['theme']}\n\n"
        + "\n".join(f"{i+1}. {s['name']}" for i, s in enumerate(segments))
        + "\n\nAll footage sourced from Wikimedia Commons under free-use licenses."
    )
    tags = ["cars", "automotive history", "car facts", "Car Professor"]

    url = upload_to_youtube(
        video_path=str(video_path),
        title=script["title"][:100],
        description=description,
        tags=tags,
        thumbnail_path=str(thumb_path),
        publish_settings={"privacyStatus": "public", "publishAt": None},
    )

    save_used_topic(topic["title"])
    print(f"\n\u2713 Done: {url}")
    return url


if __name__ == "__main__":
    run()
