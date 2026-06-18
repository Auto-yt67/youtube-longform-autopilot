"""
Image generation using Pollinations.ai - 100% free, no API key required
Generates stickman-style educational illustrations for each scene
"""

import os
import time
import urllib.request
import urllib.parse
from pathlib import Path


POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"

# Style prefix appended to every image prompt for visual consistency
STYLE_PREFIX = (
    "simple stickman educational illustration, white background, "
    "black outline stick figures, minimal color accents, "
    "clean diagram style, labeled with simple text, "
    "flat 2D drawing, educational infographic style, "
    "no shading no gradients, "
)

# Image dimensions — 16:9 for YouTube
WIDTH = 1280
HEIGHT = 720


def build_url(prompt: str, seed: int = 42) -> str:
    """Build Pollinations.ai image URL."""
    full_prompt = STYLE_PREFIX + prompt
    encoded = urllib.parse.quote(full_prompt)
    return (
        f"{POLLINATIONS_BASE}/{encoded}"
        f"?width={WIDTH}&height={HEIGHT}"
        f"&seed={seed}"
        f"&model=flux"
        f"&nologo=true"
    )


def download_image(url: str, output_path: str, retries: int = 3) -> bool:
    """Download image from Pollinations with retry logic."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CarYouTubePipeline/1.0)"
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                with open(output_path, "wb") as f:
                    f.write(response.read())
            return True
        except Exception as e:
            print(f"    Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    return False


def generate_images(scenes: list, output_dir: str) -> list:
    """
    Generate one image per scene using Pollinations.ai.
    
    Args:
        scenes: List of scene dicts with 'id' and 'image_prompt'
        output_dir: Directory to save images
    
    Returns:
        List of image paths in scene order
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    image_paths = []

    for scene in scenes:
        scene_id = scene["id"]
        prompt = scene.get("image_prompt", f"Car diagram scene {scene_id}")
        img_path = output_path / f"scene_{scene_id:03d}.png"

        if img_path.exists():
            print(f"  Scene {scene_id}: (cached)")
            image_paths.append(str(img_path))
            continue

        print(f"  Scene {scene_id}: {prompt[:60]}...")
        url = build_url(prompt, seed=scene_id * 7)
        success = download_image(url, str(img_path))

        if success:
            print(f"    ✓ Saved {img_path.name}")
        else:
            # Fallback: generate a simple colored placeholder
            print(f"    ✗ Failed — using placeholder")
            _create_placeholder(str(img_path), scene_id, prompt)

        image_paths.append(str(img_path))

        # Rate limit: Pollinations is free but throttle to be respectful
        time.sleep(1.5)

    return image_paths


def _create_placeholder(output_path: str, scene_id: int, prompt: str):
    """Create a simple text placeholder image using FFmpeg if Pollinations fails."""
    import subprocess
    text = f"Scene {scene_id}"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=white:size={WIDTH}x{HEIGHT}:rate=1",
        "-vframes", "1",
        "-vf", f"drawtext=text='{text}':fontsize=48:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
        output_path
    ]
    subprocess.run(cmd, capture_output=True)


if __name__ == "__main__":
    import json, sys
    script_file = sys.argv[1] if len(sys.argv) > 1 else "output/script.json"
    with open(script_file) as f:
        script = json.load(f)
    paths = generate_images(script["scenes"], "output/images")
    print(f"Generated {len(paths)} images")
    for p in paths:
        print(f"  {p}")
