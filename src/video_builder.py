"""
Stage 5: Video assembly.

Structure:
  1. Opening GRID - every item shown at once, held under the intro narration.
  2. For each segment: zoom from the grid into that item's cell, cut to
     full-frame photos (a new one every 10-15s), then zoom back out to the grid.
  3. Outro plays over the full grid.

Zoom frames are pre-rendered to JPEG with PIL and fed to moviepy as a lazily
loaded image sequence. Doing the resizing in moviepy instead would hold every
frame of every transition in RAM at once (~4GB for an 18-item video) and run
several times slower.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np

# moviepy 1.0.3 calls PIL.Image.ANTIALIAS internally, which was removed in
# Pillow 10+ (renamed to Image.LANCZOS). Patch it back in rather than pinning
# Pillow down, since other stages rely on the modern Pillow API.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, ImageSequenceClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip
)

W, H = 1920, 1080

# The grid is drawn at 3x output resolution so that cropping into a single
# cell still has enough pixels to fill a 1080p frame without going soft.
GRID_SCALE = 3
GW, GH = W * GRID_SCALE, H * GRID_SCALE

ZOOM_SECONDS = 0.9
ZOOM_FPS = 24

# Pacing: aim for a new photo roughly every 12.5s, clamped to a 10-15s window.
TARGET_IMAGE_SECONDS = 12.5
MIN_IMAGE_SECONDS = 10.0
MAX_IMAGE_SECONDS = 15.0

BG_COLOR = (255, 255, 255)
TEXT_COLOR = (17, 17, 17)
RING_COLOR = (17, 17, 17)

# Solid backdrop behind each cut-out car in the grid circles.
CIRCLE_BG = (238, 234, 226)

# How many of a segment's photos to test for a clean cutout. Each costs
# ~2s, so testing all 4 across 18 segments adds ~2.5 min to a run.
CUTOUT_CANDIDATES = 3

# Font search order. Drop a thick display font (Luckiest Guy, Bangers, Fredoka
# One - all free) at assets/fonts/ to get the poster look; DejaVu Bold is the
# fallback so the pipeline never hard-fails on a missing font.
_FONT_CANDIDATES = [
    Path(__file__).parent / "assets" / "fonts" / "LuckiestGuy-Regular.ttf",
    Path(__file__).parent.parent / "assets" / "fonts" / "LuckiestGuy-Regular.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _font(size: int):
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- grid build

def _choose_cols(n: int) -> int:
    """Pick a column count that keeps the grid roughly 16:9."""
    if n <= 0:
        return 1
    return max(1, min(n, round(math.sqrt(n * (W / H)))))


def _wrap_to_lines(draw, text, font, max_w):
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_label(draw, text, max_w, start_size, min_size=28, max_lines=2):
    """Shrink the label font until it fits in max_lines. Truncates as a last resort."""
    size = start_size
    while size >= min_size:
        font = _font(size)
        lines = _wrap_to_lines(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = _font(min_size)
    lines = _wrap_to_lines(draw, text, font, max_w)[:max_lines]
    if lines:
        lines[-1] = lines[-1].rstrip(" ,") + "..."
    return font, lines


def _circle_thumb(image_path: str, diameter: int) -> tuple:
    """Center-crop an image to a square and mask it into a circle."""
    img = Image.open(image_path).convert("RGB")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize(
        (diameter, diameter), Image.LANCZOS
    )
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    return img, mask


def _circle_from_rgba(rgba, diameter: int, bg) -> tuple:
    """Same as _circle_thumb but from an already-cut-out subject."""
    from cutout import on_solid
    img = on_solid(rgba, diameter, bg=bg)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    return img, mask


def prepare_cutouts(names: list, images_by_segment: dict) -> list:
    """
    Pick the best-framed photo per segment and cut its background out.

    Returns a list aligned to `names`, each entry either an RGBA cutout or
    None. None means no candidate scored well enough, and the grid falls
    back to a plain circle crop of the representative photo - a slightly
    busy circle beats a mangled cutout.

    Called once per run and reused for both the grid and the thumbnail,
    since each cutout costs ~2s.
    """
    try:
        from cutout import best_cutout
    except ImportError as e:
        print(f"  ! rembg unavailable ({e}) - using plain photo crops")
        return [None] * len(names)

    results = []
    for i, name in enumerate(names):
        candidates = images_by_segment.get(i, [])[:CUTOUT_CANDIDATES]
        if not candidates:
            results.append(None)
            continue
        print(f"    {name}:")
        rgba, path, score = best_cutout(candidates)
        if rgba is None:
            print(f"      -> no usable cutout (best {score:.2f}), using photo crop")
        else:
            print(f"      -> chose {Path(path).name} ({score:.2f})")
        results.append(rgba)
    return results


def _build_grid(names: list, rep_images: list, title: str, cutouts: list = None):
    """
    Render the full grid at GWxGH. Returns (grid_image, cell_boxes) where each
    cell box is the 16:9 region to zoom into for that item.

    `cutouts` is an optional list aligned to `names` of background-removed
    RGBA subjects. Where an entry is present the car is drawn on a solid
    backdrop; where it's None the raw photo is circle-cropped instead.
    """
    canvas = Image.new("RGB", (GW, GH), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    n = len(names)
    cols = _choose_cols(n)
    rows = math.ceil(n / cols)

    margin = int(GW * 0.03)
    title_h = int(GH * 0.16)

    # Title across the top, shrunk to fit the canvas width
    if title:
        size = int(title_h * 0.72)
        while size > 30:
            font = _font(size)
            if draw.textlength(title.upper(), font=font) <= GW - 2 * margin:
                break
            size -= 6
        font = _font(size)
        tw = draw.textlength(title.upper(), font=font)
        draw.text(((GW - tw) / 2, margin), title.upper(), font=font, fill=TEXT_COLOR)

    grid_top = title_h + margin
    cell_w = (GW - 2 * margin) / cols
    cell_h = (GH - grid_top - margin) / rows

    label_h = cell_h * 0.24
    diameter = int(min(cell_w * 0.80, (cell_h - label_h) * 0.88))
    label_start_size = max(30, int(label_h * 0.42))

    cell_boxes = []
    for i, name in enumerate(names):
        col, row = i % cols, i // cols
        cx = margin + cell_w * (col + 0.5)
        cy = grid_top + cell_h * row

        # circle image - cut-out car on a solid backdrop where we have one,
        # otherwise a plain crop of the source photo
        img_path = rep_images[i] if i < len(rep_images) else None
        rgba = cutouts[i] if cutouts and i < len(cutouts) else None
        circle_top = cy + (cell_h - label_h - diameter) / 2
        if rgba is not None:
            thumb, mask = _circle_from_rgba(rgba, diameter, CIRCLE_BG)
            canvas.paste(thumb, (int(cx - diameter / 2), int(circle_top)), mask)
        elif img_path:
            thumb, mask = _circle_thumb(img_path, diameter)
            canvas.paste(thumb, (int(cx - diameter / 2), int(circle_top)), mask)
        draw.ellipse(
            (cx - diameter / 2, circle_top, cx + diameter / 2, circle_top + diameter),
            outline=RING_COLOR, width=max(3, diameter // 90),
        )

        # label, capped at two lines
        font, lines = _fit_label(draw, name, cell_w * 0.92, label_start_size)
        ly = circle_top + diameter + label_h * 0.12
        for line in lines:
            lw = draw.textlength(line, font=font)
            draw.text((cx - lw / 2, ly), line, font=font, fill=TEXT_COLOR)
            ly += font.size * 1.1

        cell_boxes.append(_aspect_box(cx, cy + cell_h / 2, cell_w, cell_h))

    return canvas, cell_boxes


def _aspect_box(cx, cy, w, h, pad=1.18):
    """Expand a cell to a 16:9 box centred on it, clamped inside the canvas."""
    w, h = w * pad, h * pad
    if w / h < W / H:
        w = h * (W / H)
    else:
        h = w * (H / W)
    w, h = min(w, GW), min(h, GH)
    x0 = min(max(cx - w / 2, 0), GW - w)
    y0 = min(max(cy - h / 2, 0), GH - h)
    return (x0, y0, x0 + w, y0 + h)


# ------------------------------------------------------------ zoom rendering

def _ease(t: float) -> float:
    """Cubic ease-in-out - keeps the zoom from starting and stopping abruptly."""
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def _render_zoom(grid_img, from_box, to_box, out_dir: Path, tag: str):
    """Pre-render a zoom to JPEGs and return an ImageSequenceClip over them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n_frames = max(2, int(ZOOM_SECONDS * ZOOM_FPS))
    paths = []
    for f in range(n_frames):
        t = _ease(f / (n_frames - 1))
        box = tuple(from_box[j] + (to_box[j] - from_box[j]) * t for j in range(4))
        frame = grid_img.crop(tuple(int(v) for v in box)).resize((W, H), Image.LANCZOS)
        p = out_dir / f"{tag}_{f:03d}.jpg"
        frame.save(p, "JPEG", quality=88)
        paths.append(str(p))
    return ImageSequenceClip(paths, fps=ZOOM_FPS)


# --------------------------------------------------------------- still clips

def _load_rgb_clip(image_path: str) -> ImageClip:
    """
    Load an image as an ImageClip, forcing RGB. Some source photos (older
    black-and-white press photos in particular) come through as single-channel
    grayscale, which crashes moviepy's compositor when mixed with RGB clips -
    it expects every frame to have 3 color channels. Converting through PIL
    first guarantees a consistent 3-channel array regardless of the source.
    """
    img = Image.open(image_path).convert("RGB")
    return ImageClip(np.array(img))


def _cover_fit_clip(image_path: str, duration: float) -> ImageClip:
    """
    Static clip: scale the image to fully cover the WxH frame (no letterboxing,
    no distortion), center-crop any overflow, and hold it still for the full
    duration. No animation - a plain, fast-to-render still frame.
    """
    clip = _load_rgb_clip(image_path)
    img_w, img_h = clip.size
    scale = max(W / img_w, H / img_h)
    clip = clip.resize(scale)
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
    return clip.set_duration(duration)


def _plan_slots(image_paths: list, duration: float) -> list:
    """
    Decide how many photo slots fill `duration`, targeting one new photo every
    10-15s, then cycle through the available photos to fill them. A 90s segment
    with 4 photos gets 7 slots (~12.9s each), reusing photos rather than holding
    one on screen for 22s.
    """
    if duration <= 0 or not image_paths:
        return []
    slots = max(1, round(duration / TARGET_IMAGE_SECONDS))
    if duration / slots > MAX_IMAGE_SECONDS:
        slots = math.ceil(duration / MAX_IMAGE_SECONDS)
    elif duration / slots < MIN_IMAGE_SECONDS and slots > 1:
        slots = max(1, int(duration // MIN_IMAGE_SECONDS))
    per = duration / slots
    return [(image_paths[i % len(image_paths)], per) for i in range(slots)]


def _build_photo_run(image_paths: list, duration: float):
    slots = _plan_slots(image_paths, duration)
    if not slots:
        raise ValueError("No images available for this segment")
    clips = [_cover_fit_clip(p, d) for p, d in slots]
    if len(clips) == 1:
        return clips[0]
    return concatenate_videoclips(clips, method="compose")


# -------------------------------------------------------------------- build

def build_video(segments: list, audio_results: list, images_by_segment: dict,
                out_path: Path, intro_audio: dict = None, title: str = None,
                cutouts: list = None):
    """
    segments: script segments (list of {name, script, image_query})
    audio_results: from tts_engine.synthesize_segments (list of {name, wav_path, duration})
    images_by_segment: {segment_index: [local image paths]}
    intro_audio: {name, wav_path, duration} for the grid intro, or None
    title: video title, drawn across the top of the grid
    cutouts: background-removed subjects from prepare_cutouts(), or None
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = out_path.parent / "zoom_frames"

    names = [s["name"] for s in segments]
    rep_images = [
        images_by_segment.get(i, [None])[0] if images_by_segment.get(i) else None
        for i in range(len(segments))
    ]

    print("  Building grid...")
    grid_img, cell_boxes = _build_grid(names, rep_images, title or "", cutouts)
    full_box = (0, 0, GW, GH)

    grid_still_path = out_path.parent / "grid.jpg"
    grid_img.resize((W, H), Image.LANCZOS).save(grid_still_path, "JPEG", quality=90)

    clips = []

    # 1. Intro over the full grid
    if intro_audio:
        intro_a = AudioFileClip(intro_audio["wav_path"])
        intro_v = ImageClip(str(grid_still_path)).set_duration(intro_a.duration)
        clips.append(intro_v.set_audio(intro_a))

    # 2. Each segment: zoom in -> photos -> zoom out, all under its narration
    for i, seg in enumerate(segments):
        audio = AudioFileClip(audio_results[i]["wav_path"])
        images = images_by_segment.get(i, [])
        duration = audio.duration

        parts = []
        photo_time = duration
        # Only bookend with zooms if there's room for real content between them
        if duration > 2 * ZOOM_SECONDS + 4:
            parts.append(_render_zoom(grid_img, full_box, cell_boxes[i],
                                      frames_dir, f"in_{i:02d}"))
            photo_time -= 2 * ZOOM_SECONDS

        parts.append(_build_photo_run(images, photo_time))

        if duration > 2 * ZOOM_SECONDS + 4:
            parts.append(_render_zoom(grid_img, cell_boxes[i], full_box,
                                      frames_dir, f"out_{i:02d}"))

        visual = parts[0] if len(parts) == 1 else concatenate_videoclips(parts, method="compose")
        clips.append(visual.set_duration(duration).set_audio(audio))
        print(f"    [{i+1}/{len(segments)}] {seg['name']} ({duration:.0f}s)")

    # 3. Outro over the full grid - bookends the opening shot
    outro_audio = AudioFileClip(audio_results[-1]["wav_path"])
    outro_visual = ImageClip(str(grid_still_path)).set_duration(outro_audio.duration)
    clips.append(outro_visual.set_audio(outro_audio))

    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(
        str(out_path), fps=24, codec="libx264", audio_codec="aac",
        threads=4, preset="veryfast",
    )
    return out_path


if __name__ == "__main__":
    print("Run via pipeline.py - this module needs real segments/audio/images to build a video.")
