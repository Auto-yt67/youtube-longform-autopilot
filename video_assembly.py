"""
Video assembly using FFmpeg
Syncs scene images to voiceover audio using precise timestamps from Whisper alignment.
Adds smooth crossfade transitions between scenes.
"""

import subprocess
import os
import tempfile
from pathlib import Path


# Video settings
FPS = 30
WIDTH = 1280
HEIGHT = 720
TRANSITION_DURATION = 0.3  # seconds crossfade between scenes


def assemble_video(
    image_paths: list,
    scene_timings: list,
    audio_path: str,
    output_path: str,
    add_subtitles: bool = False,
):
    """
    Assemble final video from images + audio using FFmpeg.
    
    Each image is displayed for its scene's duration (from Whisper alignment),
    with crossfade transitions between scenes.
    
    Args:
        image_paths: List of image file paths in scene order
        scene_timings: List of {id, start, end, duration} dicts
        audio_path: Path to voiceover WAV
        output_path: Output MP4 path
    """
    if len(image_paths) != len(scene_timings):
        raise ValueError(
            f"Mismatch: {len(image_paths)} images but {len(scene_timings)} scene timings"
        )

    total_duration = scene_timings[-1]["end"]
    print(f"  Assembling {len(image_paths)} scenes, {total_duration:.1f}s total")

    # Build FFmpeg filter complex for crossfade transitions
    # Strategy: each image loop for its duration, then xfade between them
    inputs = []
    for img_path in image_paths:
        inputs.extend(["-loop", "1", "-i", img_path])

    # Build filter_complex
    # Scale all images to consistent size, then xfade chain
    filter_parts = []
    
    # Scale each input
    for i, timing in enumerate(scene_timings):
        dur = max(timing["duration"], 0.5)  # minimum 0.5s per scene
        filter_parts.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:white,"
            f"setsar=1,fps={FPS},"
            f"trim=duration={dur + TRANSITION_DURATION}[v{i}]"
        )

    # Chain xfade transitions
    if len(scene_timings) == 1:
        filter_parts.append(f"[v0]copy[vout]")
    else:
        # First xfade
        offset = max(scene_timings[0]["duration"] - TRANSITION_DURATION, 0.1)
        filter_parts.append(
            f"[v0][v1]xfade=transition=fade:duration={TRANSITION_DURATION}"
            f":offset={offset:.3f}[xf1]"
        )

        for i in range(2, len(scene_timings)):
            offset = sum(
                max(t["duration"] - TRANSITION_DURATION, 0.1)
                for t in scene_timings[:i]
            )
            prev = f"xf{i-1}" if i > 2 else "xf1"
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:duration={TRANSITION_DURATION}"
                f":offset={offset:.3f}[xf{i}]"
            )

        last = f"xf{len(scene_timings) - 1}" if len(scene_timings) > 2 else "xf1"
        filter_parts.append(f"[{last}]copy[vout]")

    filter_complex = ";".join(filter_parts)

    # Build full FFmpeg command
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-i", audio_path]
        + [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", f"{len(image_paths)}:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    )

    print(f"  Running FFmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FFmpeg stderr:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"FFmpeg failed with code {result.returncode}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ Video: {output_path} ({size_mb:.1f} MB)")
    return output_path


if __name__ == "__main__":
    import json, sys
    timings_file = sys.argv[1]
    images_dir = sys.argv[2]
    audio = sys.argv[3]
    output = sys.argv[4]

    with open(timings_file) as f:
        timings = json.load(f)

    images = [f"{images_dir}/scene_{t['id']:03d}.png" for t in timings]
    assemble_video(images, timings, audio, output)
