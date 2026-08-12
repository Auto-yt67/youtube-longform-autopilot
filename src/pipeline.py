"""
Full pipeline orchestrator. Runs every stage end to end:
  topic -> script -> images -> voiceover -> video -> thumbnail -> upload

Run this from GitHub Actions on a schedule, or locally with:
    python src/pipeline.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from topic_generator import generate_topic, save_used_topic
from script_writer import generate_script
from image_fetcher import download_images
from tts_engine import synthesize_segments
from video_builder import build_video
from thumbnail_generator import build_thumbnail
from youtube_upload import upload_to_youtube

WORKDIR = Path("run_output") / datetime.now().strftime("%Y%m%d_%H%M%S")


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
    (WORKDIR / "script.json").write_text(json.dumps(script, indent=2))
    segments = script["segments"]
    print(f"  {len(segments)} segments written")

    # 3. Images
    print("\n[3/6] Sourcing images from Wikimedia Commons...")
    images_by_segment = {}
    representative_images = []
    for i, seg in enumerate(segments):
        out_dir = WORKDIR / "images" / f"seg_{i:02d}"
        paths = download_images(seg["image_query"], out_dir, limit=4)
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

    # 4. Voiceover
    print("\n[4/6] Generating voiceover (Piper TTS)...")
    audio_dir = WORKDIR / "audio"
    audio_results = synthesize_segments(segments, script["outro"], audio_dir)
    total_duration = sum(a["duration"] for a in audio_results)
    print(f"  Total runtime: {total_duration / 60:.1f} min")

    # 5. Video + thumbnail
    print("\n[5/6] Assembling video...")
    video_path = WORKDIR / "final_video.mp4"
    build_video(segments, audio_results, images_by_segment, video_path)

    thumb_path = WORKDIR / "thumbnail.png"
    build_thumbnail(
        [s["name"] for s in segments],
        representative_images,
        script["title"],
        thumb_path,
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
