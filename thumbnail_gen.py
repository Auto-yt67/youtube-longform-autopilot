"""
Thumbnail generation using Pollinations.ai
High-CTR thumbnail: bold text overlay, stickman visual, bright contrasting colors
"""

import os
import time
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
WIDTH = 1280
HEIGHT = 720

THUMBNAIL_STYLE = (
    "YouTube thumbnail, high contrast, eye-catching, "
    "bold thick black outline stickman illustration, "
    "one or two flat accent colors used for emphasis, vivid background color, "
    "flat 2D design, no text, dramatic composition, thumbnail style, "
    "clean white space, consistent stickman character design, "
)

def generate_thumbnail_image(visual_prompt: str, output_path: str, seed: int = 99) -> bool:
    full_prompt = THUMBNAIL_STYLE + visual_prompt
    encoded = urllib.parse.quote(full_prompt)
    url = (
        f"{POLLINATIONS_BASE}/{encoded}"
        f"?width={WIDTH}&height={HEIGHT}"
        f"&seed={seed}"
        f"&model=flux"
        f"&nologo=true"
    )
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CarYouTubePipeline/1.0)"}
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(output_path, "wb") as f:
                    f.write(resp.read())
            return True
        except Exception as e:
            print(f"    Attempt {attempt+1} failed: {e}")
            time.sleep(3 * (attempt + 1))
    return False

def add_text_overlay(image_path: str, text: str, output_path: str):
    """Add bold text overlay to thumbnail using FFmpeg."""
    # Split text into lines if too long
    words = text.upper().split()
    if len(words) <= 3:
        line1 = " ".join(words)
        line2 = ""
    else:
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])

    # FFmpeg drawtext filter
    fontsize = 90
    if line2:
        vf = (
            f"drawtext=text='{line1}':fontsize={fontsize}:fontcolor=white:"
            f"borderw=6:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2-60,"
            f"drawtext=text='{line2}':fontsize={fontsize}:fontcolor=yellow:"
            f"borderw=6:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2+60"
        )
    else:
        vf = (
            f"drawtext=text='{line1}':fontsize={fontsize}:fontcolor=white:"
            f"borderw=6:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", image_path,
        "-vf", vf,
        "-frames:v", "1",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0

def generate_thumbnail(script: dict, output_dir: str) -> str:
    """
    Full thumbnail pipeline: generate image + add text overlay.
    Returns path to final thumbnail.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    raw_path = str(output_path / "thumbnail_raw.png")
    final_path = str(output_path / "thumbnail.png")
    
    visual_prompt = script.get("thumbnail_visual", "stickman mechanic working on car engine")
    thumbnail_text = script.get("thumbnail_text", script["title"][:30])
    
    print(f"  Generating thumbnail image...")
    success = generate_thumbnail_image(visual_prompt, raw_path)
    
    if not success:
        print("  Thumbnail image failed, creating fallback...")
        # Plain colored background fallback
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x1a1a2e:size={WIDTH}x{HEIGHT}:rate=1",
            "-vframes", "1", raw_path
        ], capture_output=True)
    
    print(f"  Adding text overlay: '{thumbnail_text}'")
    success = add_text_overlay(raw_path, thumbnail_text, final_path)
    
    if not success:
        print("  Text overlay failed, using raw image")
        import shutil
        shutil.copy(raw_path, final_path)
    
    print(f"  ✓ Thumbnail: {final_path}")
    return final_path


if __name__ == "__main__":
    import json, sys
    with open(sys.argv[1]) as f:
        script = json.load(f)
    path = generate_thumbnail(script, "output")
    print(f"Thumbnail saved: {path}")
