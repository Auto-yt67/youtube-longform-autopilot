"""
Stage 5b: Thumbnail generation.

Reuses the grid renderer from video_builder so the thumbnail and the video's
opening shot are the same design - circles, display font, two-line labels,
red accent word. The only thumbnail-specific difference is the item cap:
YouTube renders previews as small as ~210px wide, and past roughly a dozen
cells the circles and labels turn to mush.
"""

from pathlib import Path

from PIL import Image

from video_builder import _build_grid

THUMB_W, THUMB_H = 1280, 720
MAX_THUMB_ITEMS = 12


def build_thumbnail(item_names: list, image_paths: list, title: str, out_path: Path,
                    accent_word: str = None, cutouts: list = None,
                    max_items: int = MAX_THUMB_ITEMS):
    """
    item_names: list of segment names (e.g. car names)
    image_paths: matching list of one representative image path per item
    cutouts: list of {"rgba", "path"} from video_builder.prepare_cutouts()
    """
    paired = [
        (n, p, cutouts[i]["rgba"] if cutouts and i < len(cutouts) else None)
        for i, (n, p) in enumerate(zip(item_names, image_paths))
        if p and Path(p).exists()
    ][:max_items]

    if not paired:
        raise ValueError("No usable images for the thumbnail")

    names = [n for n, _, _ in paired]
    images = [p for _, p, _ in paired]
    cuts = [c for _, _, c in paired]

    canvas, _ = _build_grid(names, images, title, cuts, accent_word)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((THUMB_W, THUMB_H), Image.LANCZOS).save(out_path, quality=92)
    return out_path
