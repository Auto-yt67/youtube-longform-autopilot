"""
Image generation using WaveSpeed AI (Z-Image Turbo) — the cheapest option,
$0.005/image. Much better style/prompt adherence than free alternatives, so
images actually match the consistent stickman-diagram style and scene content.
"""

import os
import time
import json
import requests
from pathlib import Path

WAVESPEED_API_KEY = os.environ["WAVESPEED_API_KEY"]
SUBMIT_URL = "https://api.wavespeed.ai/api/v3/wavespeed-ai/z-image/turbo"
RESULT_URL_TEMPLATE = "https://api.wavespeed.ai/api/v3/predictions/{request_id}/result"

WIDTH = 1280
HEIGHT = 720

# Style prefix appended to every image prompt for visual consistency.
# Flux follows this far more reliably than Pollinations did.
STYLE_PREFIX = (
    "Simple flat 2D stickman educational diagram illustration. "
    "Bold thick black outlines on a plain white background. "
    "Stick-figure people with circular heads and simple line bodies, "
    "minimalist geometric style like a whiteboard explainer video. "
    "Use exactly one or two flat accent colors (red or blue) to highlight "
    "key parts being discussed, everything else black and white line art. "
    "Clean labeled arrows and callout lines pointing to specific objects. "
    "No shading, no gradients, no photorealism, no 3D rendering, "
    "no textures — flat vector look only. Scene: "
)


def _submit_job(prompt: str, seed: int) -> str:
    """Submit a generation job, return request_id."""
    payload = {
        "prompt": prompt,
        "size": f"{WIDTH}*{HEIGHT}",
        "seed": seed,
        "output_format": "png",
        "enable_sync_mode": False,
        "enable_base64_output": False,
    }
    headers = {
        "Authorization": f"Bearer {WAVESPEED_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(SUBMIT_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # WaveSpeed wraps the actual payload under "data"
    request_id = data.get("data", {}).get("id") or data.get("id")
    if not request_id:
        raise RuntimeError(f"No request id in response: {data}")
    return request_id


def _poll_result(request_id: str, timeout: int = 90) -> str:
    """Poll until the job completes, return the output image URL."""
    headers = {"Authorization": f"Bearer {WAVESPEED_API_KEY}"}
    url = RESULT_URL_TEMPLATE.format(request_id=request_id)
    start = time.time()

    while time.time() - start < timeout:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status")

        if status == "completed":
            outputs = data.get("outputs", [])
            if not outputs:
                raise RuntimeError(f"Job completed but no outputs: {data}")
            return outputs[0]
        elif status == "failed":
            raise RuntimeError(f"Job failed: {data.get('error', 'unknown error')}")

        time.sleep(2)

    raise TimeoutError(f"Job {request_id} did not complete within {timeout}s")


def generate_image(prompt: str, output_path: str, seed: int = 42, retries: int = 3) -> bool:
    """Generate a single image via WaveSpeed Flux Schnell and save to output_path."""
    full_prompt = STYLE_PREFIX + prompt

    for attempt in range(retries):
        try:
            request_id = _submit_job(full_prompt, seed)
            image_url = _poll_result(request_id)

            img_resp = requests.get(image_url, timeout=60)
            img_resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(img_resp.content)

            _normalize_image_aspect(output_path)
            return True
        except Exception as e:
            print(f"    Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))

    return False


def _normalize_image_aspect(image_path: str):
    """Letterbox the image onto a correctly-sized white canvas if needed."""
    try:
        from PIL import Image
    except ImportError:
        import subprocess
        subprocess.check_call(["pip", "install", "Pillow", "-q", "--break-system-packages"])
        from PIL import Image

    img = Image.open(image_path).convert("RGB")
    if img.size == (WIDTH, HEIGHT):
        return

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
    Generate one image per scene using WaveSpeed Flux Schnell.

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
        success = generate_image(prompt, str(img_path), seed=scene_id * 7)

        if success:
            print(f"    ✓ Saved {img_path.name}")
        else:
            print(f"    ✗ Failed — using placeholder")
            _create_placeholder(str(img_path), scene_id)

        image_paths.append(str(img_path))

    return image_paths


def _create_placeholder(output_path: str, scene_id: int):
    """Create a simple text placeholder image using FFmpeg if generation fails."""
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
    import sys
    script_file = sys.argv[1] if len(sys.argv) > 1 else "output/script.json"
    with open(script_file) as f:
        script = json.load(f)
    paths = generate_images(script["scenes"], "output/images")
    print(f"Generated {len(paths)} images")
    for p in paths:
        print(f"  {p}")
