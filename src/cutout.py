"""
Background removal + subject selection.

Two jobs:
  1. Cut the car out of a photo (rembg / U2Net, offline, free, CPU-only).
  2. Pick WHICH of a segment's photos to use, favouring ones showing the
     whole car rather than a cropped or distant one.

Selection matters more than it sounds. Wikimedia results for any given model
are a mix of clean press side-profiles, tight detail shots of a badge or
headlight, and wide car-show photos with the subject half behind a crowd.
Cutting out a badge close-up and dropping it in a grid circle looks broken,
so we score every candidate's mask and use the best one.
"""

from pathlib import Path

import numpy as np
from PIL import Image

_SESSION = None

# Scoring thresholds. A mask is "good" when the subject is a decent chunk of
# the frame, sits clear of the edges, is roughly car-shaped, and is one solid
# blob rather than scattered fragments.
MIN_COVERAGE = 0.06      # below this the car is a distant speck
MAX_COVERAGE = 0.78      # above this it's a crop or a detail shot
IDEAL_COVERAGE = 0.30
MIN_ASPECT = 1.05        # width/height of the subject's bounding box
MAX_ASPECT = 3.60
MIN_BBOX_FILL = 0.30     # mask area / bbox area - low means fragmented mask
EDGE_BAND = 0.015        # how close to the border counts as "touching"
EDGE_PRESENCE = 0.04     # fraction of a border line that must be subject


def _get_session():
    """Reuse one rembg session - model load is ~7s, inference is ~2s."""
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("u2net")
    return _SESSION


def cutout(image_path: str) -> Image.Image:
    """Return an RGBA image with the background removed."""
    from rembg import remove
    img = Image.open(image_path).convert("RGB")
    # Downscale first - U2Net works at 320x320 internally, so feeding it a
    # 4000px Wikimedia original just wastes time.
    work = img.copy()
    work.thumbnail((1200, 1200), Image.LANCZOS)
    return remove(work, session=_get_session())


def score_mask(rgba: Image.Image) -> tuple:
    """
    Score how well this cutout shows a whole car. Returns (score, reason).
    Higher is better; 0.0 means unusable.
    """
    alpha = np.array(rgba)[:, :, 3] > 128
    h, w = alpha.shape
    total = alpha.sum()
    if total == 0:
        return 0.0, "empty mask"

    coverage = total / (h * w)
    if coverage < MIN_COVERAGE:
        return 0.0, f"subject too small ({coverage:.0%})"
    if coverage > MAX_COVERAGE:
        return 0.0, f"subject fills frame ({coverage:.0%}) - likely cropped"

    rows, cols = np.where(alpha)
    y0, y1, x0, x1 = rows.min(), rows.max(), cols.min(), cols.max()
    bw, bh = (x1 - x0 + 1), (y1 - y0 + 1)

    score = 1.0
    reasons = []

    # Distance from ideal coverage
    score -= min(0.35, abs(coverage - IDEAL_COVERAGE) * 0.9)

    # Edge contact - the main "is the car cut off" signal
    band = max(1, int(min(h, w) * EDGE_BAND))
    edges_hit = 0
    if alpha[:band, :].mean() > EDGE_PRESENCE:
        edges_hit += 1
    if alpha[-band:, :].mean() > EDGE_PRESENCE:
        edges_hit += 1
    if alpha[:, :band].mean() > EDGE_PRESENCE:
        edges_hit += 1
    if alpha[:, -band:].mean() > EDGE_PRESENCE:
        edges_hit += 1
    if edges_hit:
        score -= 0.28 * edges_hit
        reasons.append(f"{edges_hit} edge(s) cut")

    # Shape - cars are wider than tall. A tall subject is usually a person,
    # a sign, or a front-on shot that reads badly in a circle.
    aspect = bw / bh
    if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
        score -= 0.30
        reasons.append(f"aspect {aspect:.1f}")

    # Solidity - a real car silhouette fills much of its bounding box.
    # A scattered mask (crowd, trees, reflections) fills very little.
    bbox_fill = total / float(bw * bh)
    if bbox_fill < MIN_BBOX_FILL:
        score -= 0.30
        reasons.append(f"fragmented ({bbox_fill:.0%} of bbox)")

    return max(0.0, score), ", ".join(reasons) or "clean"


def best_cutout(image_paths: list, min_score: float = 0.45):
    """
    Cut out every candidate and return the best (rgba, source_path, score).
    Returns (None, None, 0.0) if nothing clears min_score - callers should
    fall back to a plain photo crop rather than shipping a bad cutout.
    """
    best = (None, None, 0.0)
    for path in image_paths:
        try:
            rgba = cutout(path)
            score, reason = score_mask(rgba)
        except Exception as e:
            print(f"      cutout failed for {Path(path).name}: {e}")
            continue
        print(f"      {Path(path).name}: {score:.2f} ({reason})")
        if score > best[2]:
            best = (rgba, path, score)

    if best[2] < min_score:
        return (None, None, best[2])
    return best


def on_solid(rgba: Image.Image, size: int, bg=(255, 255, 255), pad=0.10) -> Image.Image:
    """
    Place a cutout on a solid square background, scaled to fit with padding
    and centred on the subject's actual bounds (not the original photo's
    frame, which may have the car off to one side).
    """
    alpha = np.array(rgba)[:, :, 3] > 128
    rows, cols = np.where(alpha)
    if len(rows) == 0:
        subject = rgba
    else:
        subject = rgba.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))

    inner = int(size * (1 - 2 * pad))
    sw, sh = subject.size
    scale = min(inner / sw, inner / sh)
    subject = subject.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)

    canvas = Image.new("RGB", (size, size), bg)
    canvas.paste(
        subject,
        ((size - subject.width) // 2, (size - subject.height) // 2),
        subject,
    )
    return canvas
