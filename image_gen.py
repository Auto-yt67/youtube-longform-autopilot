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
# Matches channel branding: bold black outlines, 1-2 accent colors (not full color),
# white background, diagram-first (not generic illustration)
STYLE_PREFIX = (
    "bold thick black outline stickman illustration, white background, "
    "exactly one or two flat accent colors used sparingly for emphasis "
    "(e.g. red or blue highlights on key parts), everything else black and white, "
    "clean technical diagram style with labeled arrows and callout lines pointing "
    "to specific parts, simple geometric shapes, no shading, no gradients, "
    "no photorealism, flat 2D vector look, educational infographic, "
    "consistent stickman character design across all panels, "
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
    """Download image from Pollinations with retry logic, then verify/fix dimensions."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CarYouTubePipeline/1.0)"
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                with open(output_path, "wb") as f:
                    f.write(response.read())
            _normalize_image_aspect(output_path)
            return True
        except Exception as e:
            print(f"    Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    return False


def _normalize_image_aspect(image_path: str):
    """
    Pollinations doesn't always return exactly WIDTHxHEIGHT, and some models
    silently crop or distort the requested aspect ratio. This re-letterboxes
    the actual downloaded image onto a correctly-sized white canvas instead
    of letting a mismatched-aspect image get force-stretched later.
    """
    try:
        from PIL import Image
    except ImportError:
        import subprocess
        subprocess.check_call(["pip", "install", "Pillow", "-q", "--break-system-packages"])
        from PIL import Image

    img = Image.open(image_path).convert("RGB")
    if img.size == (WIDTH, HEIGHT):
        return  # already correct, nothing to do

    # Scale to fit within target box, preserving aspect ratio (no stretch)
    src_ratio = img.width / img.height
    target_ratio = WIDTH / HEIGHT
    if src_ratio > target_ratio:
        new_w = WIDTH
        new_h = round(WIDTH / src_ratio)
    else:
        new_h = HEIGHT
        new_w = round(HEIGHT * src_ratio)

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    offset = ((WIDTH - new_w) // 2, (HEIGHT - new_h) // 2)
    canvas.paste(resized, offset)
    canvas.save(image_path)


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
