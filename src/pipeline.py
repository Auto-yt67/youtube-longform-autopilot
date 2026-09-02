"""
Full pipeline orchestrator. Runs every stage end to end:
  topic -> script -> images -> voiceover -> grid -> video -> thumbnail -> upload

Run this from GitHub Actions on a schedule, or locally with:
    python src/pipeline.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from topic_generator import generate_topic, save_used_topic
from script_writer import generate_script, generate_additional_segments
from image_fetcher import download_images
from tts_engine import synthesize_segments
from grid_renderer import render_grid, MAX_GRID_ITEMS
from video_builder import build_video
from thumbnail_generator import build_thumbnail
from youtube_upload import upload_to_youtube

WORKDIR = Path("run_output") / datetime.now().strftime("%Y%m%d_%H%M%S")

WORDS_PER_MINUTE = 140
TARGET_MIN_SECONDS = 8 * 60 + 30
MAX_TOPUP_ROUNDS = 4
SEGMENTS_PER_TOPUP = 3
MAX_SEGMENTS = 15


def _estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_MINUTE * 60


def _total_estimated_seconds(script: dict) -> float:
    total = _estimate_seconds(script["intro"])
    total += sum(_estimate_seconds(s["script"]) for s in script["segments"])
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

    estimated = _total_estimated_seconds(script)
    print(f"  Estimated runtime: {estimated / 60:.1f} min (target: {TARGET_MIN_SECONDS / 60:.1f} min)")
    rounds = 0
    while estimated < TARGET_MIN_SECONDS and rounds < MAX_TOPUP_ROUNDS and len(segments) < MAX_SEGMENTS:
        rounds += 1
        room_left = MAX_SEGMENTS - len(segments)
        request_count = min(SEGMENTS_PER_TOPUP, room_left)
        print(f"  Below target - requesting {request_count} more segments (round {rounds})...")
        existing_names = [s["name"] for s in segments]
        extra = generate_additional_segments(topic, existing_names, request_count)
        segments.extend(extra)
        script["segments"] = segments
        estimated = _total_estimated_seconds(script)
        print(f"  New estimated runtime: {estimated / 60:.1f} min ({len(segments)} segments total)")

    if len(segments) >= MAX_SEGMENTS and estimated < TARGET_MIN_SECONDS:
        print(f"  Hit the {MAX_SEGMENTS}-segment cap before reaching target - proceeding anyway.")

    (WORKDIR / "script.json").write_text(json.dumps(script, indent=2))

    # 3. Images
    print("\n[3/6] Sourcing images from Wikimedia Commons...")

    intro_dir = WORKDIR / "images" / "intro"
    try:
        intro_images = download_images(script["intro_image_query"], intro_dir, limit=4)
    except Exception as e:
        print(f"  ! unexpected failure sourcing intro images ({e}) - treating as 0 images")
        intro_images = []
    print(f"  Intro: {len(intro_images)} images")

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

    # Drop segments with zero usable images
    usable = [i for i in range(len(segments)) if images_by_segment[i]]
    if len(usable) < len(segments):
        segments = [segments[i] for i in usable]
        images_by_segment = {new_i: images_by_segment[old_i] for new_i, old_i in enumerate(usable)}
        representative_images = [representative_images[i] for i in usable]

    if not intro_images and images_by_segment.get(0):
        intro_images = images_by_segment[0]

    # 4. Voiceover
    print("\n[4/6] Generating voiceover (Piper TTS)...")
    audio_dir = WORKDIR / "audio"
    audio_results = synthesize_segments(segments, script["intro"], script["outro"], audio_dir)
    total_duration = sum(a["duration"] for a in audio_results)
    print(f"  Total runtime: {total_duration / 60:.1f} min")

    # 5. Grid + video + thumbnail
    print("\n[5/6] Rendering grid, assembling video + thumbnail...")
    # The grid uses only the items that will actually appear in it (first
    # MAX_GRID_ITEMS, complete rows). The video's zoom cells come from the same
    # render, so grid and zoom stay perfectly aligned.
    grid_names = [s["name"] for s in segments]
    grid_reps = representative_images
    # Video's opening grid: no colored accent word (accent stays on the thumbnail only)
    grid_canvas, cells = render_grid(grid_names, grid_reps, script["title"], accent=False)
    grid_path = WORKDIR / "grid.png"
    grid_canvas.save(grid_path)

    # Only the segments represented in the grid get a zoom target; any beyond
    # the grid cap still play with their own photos (cell=None -> no zoom).
    video_path = WORKDIR / "final_video.mp4"
    build_video(segments, audio_results, images_by_segment, str(grid_path), cells, video_path)

    thumb_path = WORKDIR / "thumbnail.png"
    build_thumbnail(grid_names, grid_reps, script["title"], thumb_path)
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
