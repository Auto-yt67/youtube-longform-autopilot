"""
Circle cutout builder.

Takes a raw photo and produces the reference-style circle: the car with its
background removed (via the lightweight u2netp rembg model), the WHOLE subject
fit inside the circle with a little padding, sitting on a slightly-off-white
fill, ringed with a black outline.

Uses u2netp specifically (~4MB) rather than rembg's default bria-rmbg model
(~1GB) - the default OOM-kills on CI runners. u2netp is the small, CPU-cheap
variant that still cuts cleanly.
"""

from PIL import Image, ImageDraw, ImageOps
import numpy as np

OFF_WHITE = (250, 246, 232)   # warmer cream (was 245,243,238 - too grey/white)
RING_COLOR = (20, 20, 20)
RING_WIDTH = 6                # thinner black outline (was 10)
SUBJECT_FILL = 0.82      # fraction of the circle diameter the subject's longest side fills
                          # (< 1.0 so the WHOLE car fits with breathing room, per the reference)

_session = None


def _get_session():
    """Lazily create the rembg session so importing this module is cheap and
    the model only loads if cutouts are actually used."""
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session("u2netp")
    return _session


def _remove_bg(img: Image.Image) -> Image.Image:
    from rembg import remove
    return remove(img.convert("RGB"), session=_get_session()).convert("RGBA")


def _trim_to_subject(rgba: Image.Image) -> Image.Image:
    """Crop to the bounding box of the non-transparent subject, so scaling
    later is based on the car itself, not the original photo's framing."""
    alpha = np.array(rgba.split()[-1])
    ys, xs = np.where(alpha > 20)
    if len(xs) == 0 or len(ys) == 0:
        return rgba  # nothing detected - return as-is
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    return rgba.crop((x0, y0, x1 + 1, y1 + 1))


def make_circle(img_path: str, size: int, cutout: bool = True) -> Image.Image:
    """
    Return an RGBA circle of diameter `size`: off-white fill, black ring, and
    the subject centered inside. If cutout=True the background is removed and
    the whole subject is fit with padding; if the cutout fails or is disabled,
    falls back to a normal center-cropped photo fill.
    """
    circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    # off-white background disc
    fill = Image.new("RGBA", (size, size), OFF_WHITE + (255,))
    circle.paste(fill, (0, 0), mask)

    subject = None
    if cutout:
        try:
            src = Image.open(img_path)
            cut = _trim_to_subject(_remove_bg(src))
            # scale the whole subject to fit within SUBJECT_FILL of the diameter
            target = int(size * SUBJECT_FILL)
            cut.thumbnail((target, target), Image.LANCZOS)
            subject = cut
        except Exception as e:
            print(f"  ! cutout failed for {img_path} ({e}) - using plain photo fill")
            subject = None

    if subject is not None:
        # center the subject on the disc
        sx = (size - subject.width) // 2
        sy = (size - subject.height) // 2
        circle.alpha_composite(subject, (sx, sy))
    else:
        # fallback: center-cropped photo filling the circle (old behavior)
        photo = ImageOps.fit(Image.open(img_path).convert("RGB"), (size, size), Image.LANCZOS)
        circle.paste(photo, (0, 0), mask)

    # black outline ring
    ring = ImageDraw.Draw(circle)
    ring.ellipse(
        (RING_WIDTH // 2, RING_WIDTH // 2, size - 1 - RING_WIDTH // 2, size - 1 - RING_WIDTH // 2),
        outline=RING_COLOR, width=RING_WIDTH,
    )
    return circle
