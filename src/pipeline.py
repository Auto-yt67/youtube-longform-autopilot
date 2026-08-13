"""
Full pipeline orchestrator. Runs every stage end to end:
  topic -> script -> images -> voiceover -> intro -> video -> thumbnail -> upload

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
from tts_engine import synthesize, get_wav_duration
from video_builder import build_video, prepare_cutouts
from thumbnail_generator import build_thumbnail
from youtube_upload import upload_to_youtube

WORKDIR = Path("run_output") / datetime.now().strftime("%Y%m%d_%H%M%S")

# Word-count estimate, used only to decide how much script to write BEFORE
# running TTS. It tracks tts_engine.LENGTH_SCALE (~220 wpm at 0.64) but it is
# only ever a guess - the real floor is enforced against measured audio below.
WORDS_PER_MINUTE = 220
TARGET_MIN_SECONDS = 8 * 60 + 30

# HARD FLOOR on the finished video, checked against actual synthesized audio
# rather than estimated word counts. If the voice turns out faster than
# WORDS_PER_MINUTE assumes, this catches it and writes more script; the
# estimate alone would happily ship a 6-minute video.
MIN_VIDEO_SECONDS = 8 * 60

MAX_TOPUP_ROUNDS = 4
MAX_LENGTH_ROUNDS = 4
SEGMENTS_PER_TOPUP = 3

# Counts that tile into a full rectangle with no ragged last row. 19 items
# can only be 19x1 or 1x19, so a 19-item script ships 18 and the odd one out
# gets cut - a clean grid is worth ~45 seconds of runtime.
GRIDDABLE_COUNTS = [8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 24]


def _estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_MINUTE * 60


def _total_estimated_seconds(script: dict) -> float:
    total = sum(_estimate_seconds(s["script"]) for s in script["segments"])
    total += _estimate_seconds(script["outro"])
    return total


def _retitle_count(title: str, n: int) -> str:
    """
    Rewrite the leading number in a title to match the real segment count.
    "12 Forgotten Concept Cars..." shipping only 10 items reads as a mistake
    to anyone counting, and viewers do count.
    """
    words = title.split()
    if words and words[0].isdigit():
        words[0] = str(n)
        return " ".join(words)
    return title


def _trim_to_griddable(segments: list) -> list:
    """Drop trailing segments until the count tiles evenly."""
    n = len(segments)
    if n in GRIDDABLE_COUNTS:
        return segments
    smaller = [c for c in GRIDDABLE_COUNTS if c < n]
    if not smaller:
        return segments
    target = max(smaller)
    dropped = [s["name"] for s in segments[target:]]
    print(f"  Trimming {n} -> {target} for an even grid (cut: {', '.join(dropped)})")
    return segments[:target]


def _next_griddable(n: int) -> int:
    """Smallest griddable count above n - the target when a video runs short."""
    larger = [c for c in GRIDDABLE_COUNTS if c > n]
    return larger[0] if larger else n + 2


def _source_images_for(segments: list, workdir: Path, start: int = 0):
    """Fetch images for segments[start:], storing paths on each segment dict."""
    for i in range(start, len(segments)):
        seg = segments[i]
        out_dir = workdir / "images" / f"seg_{i:02d}"
        try:
            paths = download_images(seg["image_query"], out_dir, limit=4)
        except Exception as e:
            print(f"  ! unexpected failure sourcing images for '{seg['name']}' ({e}) - treating as 0 images")
            paths = []
        if not paths:
            print(f"  ! No clear-license images found for '{seg['name']}' "
                  f"(query: {seg['image_query']}) - segment will be skipped")
        seg["_images"] = paths
        print(f"  {seg['name']}: {len(paths)} images")


def _synthesize_missing(segments: list, audio_dir: Path):
    """
    Synthesize any segment that doesn't have audio yet, caching the result on
    the segment dict. Re-running this after adding segments only pays for the
    new ones - TTS is the slowest stage, so re-synthesizing everything on each
    length-check round would multiply run time.
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    for i, seg in enumerate(segments):
        if seg.get("_wav"):
            continue
        wav_path = audio_dir / f"segment_{i:02d}.wav"
        synthesize(seg["script"], wav_path)
        seg["_wav"] = str(wav_path)
        seg["_duration"] = get_wav_duration(wav_path)


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

    # Top up if the script looks short. This is the cheap estimate pass -
    # writing script is fast, TTS is slow, so overshoot here rather than
    # discovering the shortfall after synthesis.
    estimated = _total_estimated_seconds(script)
    print(f"  Estimated runtime: {estimated / 60:.1f} min (target: {TARGET_MIN_SECONDS / 60:.1f} min)")
    rounds = 0
    while estimated < TARGET_MIN_SECONDS and rounds < MAX_TOPUP_ROUNDS:
        rounds += 1
        print(f"  Below target - requesting {SEGMENTS_PER_TOPUP} more segments (round {rounds})...")
        extra = generate_additional_segments(topic, [s["name"] for s in segments], SEGMENTS_PER_TOPUP)
        segments.extend(extra)
        script["segments"] = segments
        estimated = _total_estimated_seconds(script)
        print(f"  New estimated runtime: {estimated / 60:.1f} min ({len(segments)} segments total)")

    # 3. Images
    #
    # Segments with no clear-license images get dropped, which used to push
    # finished videos below target. So this loops: source, drop, re-estimate,
    # and request replacements for anything lost.
    print("\n[3/6] Sourcing images from Wikimedia Commons...")
    _source_images_for(segments, WORKDIR)

    refill_rounds = 0
    while refill_rounds < MAX_TOPUP_ROUNDS:
        kept = [s for s in segments if s.get("_images")]
        dropped = len(segments) - len(kept)
        segments = kept
        script["segments"] = segments

        estimated = _total_estimated_seconds(script)
        if estimated >= TARGET_MIN_SECONDS:
            if dropped:
                print(f"  Dropped {dropped} segment(s); still at {estimated / 60:.1f} min - no refill needed")
            break

        refill_rounds += 1
        need = max(SEGMENTS_PER_TOPUP, dropped)
        print(f"  After drops: {len(segments)} segments, {estimated / 60:.1f} min "
              f"- requesting {need} replacement(s) (round {refill_rounds})...")
        extra = generate_additional_segments(topic, [s["name"] for s in segments], need)
        first_new = len(segments)
        segments.extend(extra)
        script["segments"] = segments
        _source_images_for(segments, WORKDIR, start=first_new)

    segments = _trim_to_griddable(segments)
    script["segments"] = segments

    # 4. Voiceover, with a hard length floor checked against real audio.
    #
    # The word-count estimate above is a guess that depends on LENGTH_SCALE and
    # the voice's own pace; when it's optimistic, videos ship short. This loop
    # measures the synthesized wavs and writes more segments until the real
    # runtime clears MIN_VIDEO_SECONDS, always landing on a griddable count so
    # the grid stays a full rectangle.
    print("\n[4/6] Generating voiceover (Piper TTS)...")
    audio_dir = WORKDIR / "audio"
    _synthesize_missing(segments, audio_dir)

    outro_wav = audio_dir / "outro.wav"
    synthesize(script["outro"], outro_wav)
    outro_duration = get_wav_duration(outro_wav)

    length_rounds = 0
    while length_rounds < MAX_LENGTH_ROUNDS:
        spoken = sum(s["_duration"] for s in segments) + outro_duration
        print(f"  Measured runtime: {spoken / 60:.1f} min "
              f"({len(segments)} segments, floor {MIN_VIDEO_SECONDS / 60:.0f} min)")
        if spoken >= MIN_VIDEO_SECONDS:
            break

        length_rounds += 1
        target = _next_griddable(len(segments))
        need = target - len(segments)
        print(f"  Short by {(MIN_VIDEO_SECONDS - spoken) / 60:.1f} min - "
              f"adding {need} segment(s) to reach {target} (round {length_rounds})...")

        extra = generate_additional_segments(topic, [s["name"] for s in segments], need)
        first_new = len(segments)
        segments.extend(extra)
        _source_images_for(segments, WORKDIR, start=first_new)

        segments = [s for s in segments if s.get("_images")]
        segments = _trim_to_griddable(segments)
        script["segments"] = segments
        _synthesize_missing(segments, audio_dir)
    else:
        spoken = sum(s["_duration"] for s in segments) + outro_duration
        if spoken < MIN_VIDEO_SECONDS:
            print(f"  ! Still {spoken / 60:.1f} min after {MAX_LENGTH_ROUNDS} rounds - shipping anyway")

    # Title says "12 Concept Cars" but drops/refills change the count, so
    # rewrite the leading number to match what actually ships.
    script["title"] = _retitle_count(script["title"], len(segments))
    print(f"  Final: {len(segments)} segments - \"{script['title']}\"")

    images_by_segment = {i: s["_images"] for i, s in enumerate(segments)}
    representative_images = [s["_images"][0] for s in segments]
    audio_results = [
        {"name": s["name"], "wav_path": s["_wav"], "duration": s["_duration"]}
        for s in segments
    ]
    audio_results.append({
        "name": "outro", "wav_path": str(outro_wav), "duration": outro_duration,
    })

    # 4b. Intro - written HERE, after the segment list is finally settled.
    # Top-ups, image drops, trimming, and the length loop above can all change
    # which items ship; an intro written any earlier would promise cars that
    # never appear on screen.
    print("\n[4b/6] Writing intro narration...")
    intro_text = generate_intro(topic, [s["name"] for s in segments])
    script["intro"] = intro_text
    print(f"  Intro: {len(intro_text.split())} words")

    intro_wav = audio_dir / "intro.wav"
    synthesize(intro_text, intro_wav)
    intro_audio = {
        "name": "intro",
        "wav_path": str(intro_wav),
        "duration": get_wav_duration(intro_wav),
    }
    total_duration = intro_audio["duration"] + sum(a["duration"] for a in audio_results)
    print(f"  Total runtime: {total_duration / 60:.1f} min")

    (WORKDIR / "script.json").write_text(json.dumps(
        {k: v for k, v in script.items()}, indent=2, default=str
    ))

    # 5. Video + thumbnail
    print("\n[5/6] Assembling video...")

    # Cut out the cars once here rather than inside both the video and the
    # thumbnail builders - each cutout costs ~2s and both need the same set.
    print("  Selecting and cutting out subjects...")
    cutouts = prepare_cutouts([s["name"] for s in segments], images_by_segment)
    print(f"  {sum(c['rgba'] is not None for c in cutouts)}/{len(cutouts)} usable cutouts")

    accent_word = pick_accent_word(script["title"])
    print(f"  Accent word: {accent_word}")

    video_path = WORKDIR / "final_video.mp4"
    build_video(segments, audio_results, images_by_segment, video_path,
                intro_audio=intro_audio, title=script["title"], cutouts=cutouts)

    thumb_path = WORKDIR / "thumbnail.png"
    build_thumbnail(
        [s["name"] for s in segments],
        representative_images,
        script["title"],
        thumb_path,
        accent_word=accent_word,
        cutouts=cutouts,
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

    save_used_topic(f"{topic.get('category', 'Unknown')}|{topic['title']}")
    print(f"\n\u2713 Done: {url}")
    return url


if __name__ == "__main__":
    run()
