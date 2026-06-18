"""
Car Education YouTube Automation Pipeline
Full pipeline: Topic → Script → Voiceover → Images → Video → Upload
"""

import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

from script_gen import generate_script
from image_gen import generate_images
from tts import generate_voiceover
from timestamp_align import align_scenes_to_audio
from video_assembly import assemble_video
from youtube_upload import upload_to_youtube


def run_pipeline(topic: str, output_dir: str = "output", skip_upload: bool = False):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🚗 Car YouTube Pipeline")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")

    # ── Step 1: Script Generation ──────────────────────────────
    print("📝 Step 1/6: Generating script...")
    script_path = output_path / "script.json"
    if script_path.exists():
        print("  (using cached script.json)")
        with open(script_path) as f:
            script = json.load(f)
    else:
        script = generate_script(topic)
        with open(script_path, "w") as f:
            json.dump(script, f, indent=2)
    print(f"  ✓ {len(script['scenes'])} scenes generated")

    # ── Step 2: Voiceover ──────────────────────────────────────
    print("\n🎙️  Step 2/6: Generating voiceover...")
    audio_path = output_path / "voiceover.wav"
    if audio_path.exists():
        print("  (using cached voiceover.wav)")
    else:
        generate_voiceover(script["narration"], str(audio_path))
    print(f"  ✓ Voiceover saved to {audio_path}")

    # ── Step 3: Timestamp Alignment ────────────────────────────
    print("\n⏱️  Step 3/6: Aligning scenes to audio timestamps...")
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

    # ── Step 4: Image Generation ───────────────────────────────
    print("\n🖼️  Step 4/6: Generating images...")
    images_dir = output_path / "images"
    images_dir.mkdir(exist_ok=True)
    image_paths = generate_images(script["scenes"], str(images_dir))
    print(f"  ✓ {len(image_paths)} images generated")

    # ── Step 5: Video Assembly ─────────────────────────────────
    print("\n🎬 Step 5/6: Assembling video...")
    video_path = output_path / "final_video.mp4"
    assemble_video(
        image_paths=image_paths,
        scene_timings=scene_timings,
        audio_path=str(audio_path),
        output_path=str(video_path),
    )
    print(f"  ✓ Video saved to {video_path}")

    # ── Step 6: YouTube Upload ─────────────────────────────────
    if skip_upload:
        print("\n⏭️  Step 6/6: Skipping upload (--no-upload flag set)")
    else:
        print("\n📤 Step 6/6: Uploading to YouTube...")
        video_url = upload_to_youtube(
            video_path=str(video_path),
            title=script["title"],
            description=script["description"],
            tags=script["tags"],
        )
        print(f"  ✓ Uploaded: {video_url}")

    print(f"\n{'='*60}")
    print("✅ Pipeline complete!")
    print(f"{'='*60}\n")
    return str(video_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Car YouTube Automation Pipeline")
    parser.add_argument("topic", help='Video topic, e.g. "How does a car engine work?"')
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--no-upload", action="store_true", help="Skip YouTube upload")
    args = parser.parse_args()

    run_pipeline(args.topic, args.output, skip_upload=args.no_upload)
