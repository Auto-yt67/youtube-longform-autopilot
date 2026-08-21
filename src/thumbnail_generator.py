"""
Stage 5b: Thumbnail generation.
Builds a grid-of-circles thumbnail (image + bold label per item) matching
the reference style - a quick visual index of everything covered.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

THUMB_W, THUMB_H = 1280, 720
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # present on Ubuntu runners


def _circle_crop(img_path: str, size: int) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(img, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0), mask)
    return out


def _label(draw: ImageDraw.Draw, text: str, cx: int, top: int, max_width: int, font_size: int = 26):
    font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
    words = text.upper().split()
    lines, line = [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) > max_width and line:
            lines.append(line)
            line = w
        else:
            line = test
    lines.append(line)

    y = top
    for line in lines:
        w = draw.textlength(line, font=font)
        x = cx - w / 2
        # simple black outline for readability over any image
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((x + dx, y + dy), line, font=font, fill="black")
        draw.text((x, y), line, font=font, fill="white")
        y += font_size + 4


def build_thumbnail(item_names: list, image_paths: list, title: str, out_path: Path, max_items: int = 15):
    """
    item_names: list of segment names (e.g. car names)
    image_paths: matching list of one representative image path per item
    """
    canvas = Image.new("RGB", (THUMB_W, THUMB_H), "white")
    draw = ImageDraw.Draw(canvas)

    items = list(zip(item_names, image_paths))[:max_items]
    cols = 5
    rows = (len(items) + cols - 1) // cols
    cell_w = THUMB_W // cols
    cell_h = THUMB_H // rows
    circle_size = int(min(cell_w, cell_h) * 0.55)

    for idx, (name, img_path) in enumerate(items):
        col, row = idx % cols, idx // cols
        cx = col * cell_w + cell_w // 2
        cy = row * cell_h + int(cell_h * 0.32)

        if img_path and Path(img_path).exists():
            circle = _circle_crop(img_path, circle_size)
            canvas.paste(circle, (cx - circle_size // 2, cy - circle_size // 2), circle)

        _label(draw, name, cx, cy + circle_size // 2 + 8, cell_w - 20)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
    return out_path
