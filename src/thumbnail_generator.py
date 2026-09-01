"""
Stage 5b: Thumbnail generation.
Thin wrapper over the shared grid_renderer, so the thumbnail is pixel-identical
to the video's opening grid shot, just downscaled to YouTube thumbnail size.
"""

from pathlib import Path
from PIL import Image

from grid_renderer import render_grid

THUMB_W, THUMB_H = 1280, 720


def build_thumbnail(item_names: list, image_paths: list, title: str, out_path: Path):
    canvas, _cells = render_grid(item_names, image_paths, title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((THUMB_W, THUMB_H), Image.LANCZOS).save(out_path, quality=92)
    return out_path
