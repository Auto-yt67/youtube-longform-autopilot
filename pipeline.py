"""
Car Education YouTube Automation Pipeline
Fully autonomous — picks its own topic, formula, and optimal posting time.
"""

import os
import sys
import json
import argparse
from pathlib import Path

from script_gen import generate_script
from image_gen import generate_images
from tts import generate_voiceover
from timestamp_align import align_scenes_to_audio
from video_assembly import assemble_video
from thumbnail_gen import generate_thumbnail
from optimal_time import get_optimal_publish_time, get_privacy_and_schedule
from youtube_upload import upload_to_youtube


def run_pipeline(output_dir: str = "output", skip_upload: bool = False,
                 formula_key: str = None, topic: str = None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🚗 Car YouTube Pipeline — Fully Autonomous")
    print(f"{'='*60}\n")

    # ── Step 1: Script ─────────────────────────────────────────
    print("📝 Step 1/7: Generating script...")
    script_path = output_path / "script.json"
    if script_path.exists():
        print("  (using cached script.json)")
        with open(script_path) as f:
            script = json.load(f)
    else:
        script = generate_script(formula_key, topic)
        with open(script_path, "w") as f:
            json.dump(script, f, indent=2)

    print(f"  ✓ Formula: {script['formula']}")
    print(f"  ✓ Topic: {script['topic']}")
    print(f"  ✓ Title: {script['title']}")
    print(f"  ✓ {len(script['scenes'])} scenes")

    # ── Step 2: Voiceover ──────────────────────────────────────
    print("\n🎙️  Step 2/7: Generating voiceover...")
    audio_path = output_path / "voiceover.wav"
    if audio_path.exists():
        print("  (using cached voiceover.wav)")
    else:
        generate_voiceover(script["narration"], str(audio_path))

    # ── Step 3: Timestamp Alignment ────────────────────────────
    print("\n⏱️  Step 3/7: Aligning scenes to audio...")
    timestamps_path = output_path / "timestamps.json"
    if timestamps_path.exists():
        print("  (using cached timestamps.json)")
        with open(timestamps_path) as f:
            scene_timings = json.load(f)
    else:
        scene_timings = align_scenes_to_audio(str(audio_path), script["scenes"])
        with open(timestamps_path, "w") as f:
            json.dump(scene_timings, f, indent=2)
    print(f"  ✓ {len(scene_timings)} scenes aligned")

    # ── Step 4: Images ─────────────────────────────────────────
    print("\n🖼️  Step 4/7: Generating scene images...")
    images_dir = output_path / "images"
    images_dir.mkdir(exist_ok=True)
    image_paths = generate_images(script["scenes"], str(images_dir))
    print(f"  ✓ {len(image_paths)} images generated")

    # ── Step 5: Thumbnail ──────────────────────────────────────
    print("\n🎨 Step 5/7: Generating thumbnail...")
    thumbnail_path = generate_thumbnail(script, str(output_path))

    # ── Step 6: Video Assembly ─────────────────────────────────
    print("\n🎬 Step 6/7: Assembling video...")
    video_path = output_path / "final_video.mp4"
    assemble_video(
        image_paths=image_paths,
        scene_timings=scene_timings,
        audio_path=str(audio_path),
        output_path=str(video_path),
    )

    # ── Step 7: Upload ─────────────────────────────────────────
    if skip_upload:
        print("\n⏭️  Step 7/7: Skipping upload")
    else:
        print("\n📤 Step 7/7: Uploading to YouTube...")
        publish_info = get_optimal_publish_time()
        publish_settings = get_privacy_and_schedule(publish_info)
        
        print(f"  Posting: {publish_info['scheduled_time_readable']}")
        print(f"  Reason: {publish_info['reason']}")

        video_url = upload_to_youtube(
            video_path=str(video_path),
            title=script["title"],
            description=script["description"],
            tags=script.get("tags", []),
            thumbnail_path=thumbnail_path,
            publish_settings=publish_settings,
        )
        print(f"  ✓ {video_url}")

    print(f"\n{'='*60}")
    print("✅ Pipeline complete!")
    print(f"  Formula: {script['formula']}")
    print(f"  Topic: {script['topic']}")
    print(f"  Title: {script['title']}")
    print(f"{'='*60}\n")
    return str(video_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--formula", default=None, help="Force a specific formula key")
    parser.add_argument("--topic", default=None, help="Force a specific topic")
    args = parser.parse_args()
    run_pipeline(args.output, skip_upload=args.no_upload,
                 formula_key=args.formula, topic=args.topic)
