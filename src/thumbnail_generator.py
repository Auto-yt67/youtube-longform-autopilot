"""
Stage 5b: Thumbnail generation.

Reuses the exact grid renderer from video_builder so the thumbnail and the
video's opening shot are the same design - circles, display font, two-line
labels. The only differences are thumbnail-specific: the item list is capped
so cells stay legible at YouTube's small preview size, and the title gets a
red accent word for contrast.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

from video_builder import _build_grid, _font, GW, GH

THUMB_W, THUMB_H = 1280, 720

# YouTube renders thumbnails as small as ~210px wide in sidebars. Past roughly
# a dozen cells the circles and labels turn to mush, so the thumbnail shows a
# subset even when the video covers more items.
MAX_THUMB_ITEMS = 12

ACCENT_COLOR = (214, 26, 26)
TEXT_COLOR = (17, 17, 17)


def _draw_accent_title(canvas: Image.Image, title: str, accent_word: str = None):
    """
    Draw the title across the reserved top band, with one word in red.
    `accent_word` comes from the model (script_writer.pick_accent_word); if it
    isn't supplied or doesn't match anything in the title, the longest word is
    used so there's always exactly one word in red.
    """
    draw = ImageDraw.Draw(canvas)
    margin = int(GW * 0.03)
    title_h = int(GH * 0.16)
    words = title.upper().split()
    if not words:
        return

    accent_idx = None
    if accent_word:
        target = accent_word.strip(".,:!?-").upper()
        for i, word in enumerate(words):
            if word.strip(".,:!?-") == target:
                accent_idx = i
                break
    if accent_idx is None:
        accent_idx = max(range(len(words)), key=lambda i: len(words[i]))

    size = int(title_h * 0.72)
    while size > 30:
        font = _font(size)
        if draw.textlength(" ".join(words), font=font) <= GW - 2 * margin:
            break
        size -= 6
    font = _font(size)

    total_w = draw.textlength(" ".join(words), font=font)
    space_w = draw.textlength(" ", font=font)
    x = (GW - total_w) / 2
    y = margin

    for i, word in enumerate(words):
        color = ACCENT_COLOR if i == accent_idx else TEXT_COLOR
        draw.text((x, y), word, font=font, fill=color)
        x += draw.textlength(word, font=font) + space_w


def build_thumbnail(item_names: list, image_paths: list, title: str, out_path: Path,
                    accent_word: str = None, cutouts: list = None,
                    max_items: int = MAX_THUMB_ITEMS):
    """
    item_names: list of segment names (e.g. car names)
    image_paths: matching list of one representative image path per item
    cutouts: background-removed subjects from video_builder.prepare_cutouts()
    """
    paired = [
        (n, p, cutouts[i] if cutouts and i < len(cutouts) else None)
        for i, (n, p) in enumerate(zip(item_names, image_paths))
        if p and Path(p).exists()
    ][:max_items]

    if not paired:
        raise ValueError("No usable images for the thumbnail")

    names = [n for n, _, _ in paired]
    images = [p for _, p, _ in paired]
    cuts = [c for _, _, c in paired]

    # Build with an empty title so the top band is reserved but blank, then
    # draw the accented title into it ourselves.
    canvas, _ = _build_grid(names, images, "", cuts)
    _draw_accent_title(canvas, title, accent_word)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((THUMB_W, THUMB_H), Image.LANCZOS).save(out_path, quality=92)
    return out_path
