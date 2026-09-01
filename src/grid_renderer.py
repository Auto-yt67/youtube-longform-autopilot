"""
Shared grid renderer.

This is the heart of the "catalog" format: a single function that renders the
grid of circular photos with a title, used for BOTH the thumbnail and the
video's opening shot. It also returns the pixel-space bounding box of each
grid cell, so the video builder can zoom into each item's region in turn.

Keeping this in one place guarantees the thumbnail and the video's opening
grid are visually identical - same layout, same circles, same labels.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Full-resolution canvas (video frame size). The thumbnail is just this,
# downscaled to 1280x720.
GRID_W, GRID_H = 1920, 1080
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # present on Ubuntu runners

TITLE_AREA_HEIGHT = 150   # reserved band at the top for the title text
GRID_TOP = TITLE_AREA_HEIGHT + 12
GRID_COLS = 6
ACCENT_COLOR = "#e02020"
MAX_GRID_ITEMS = 12


def _circle_crop(img_path: str, size: int) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(img, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0), mask)
    return out


def _wrap_words(draw, words, font, max_width):
    lines, current = [], []
    for w in words:
        test = current + [w]
        if draw.textlength(" ".join(test), font=font) > max_width and current:
            lines.append(current)
            current = [w]
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _draw_title(draw, title, canvas_w):
    """Bold uppercase title, centered. Colors the word after a leading number
    as a red accent (e.g. "12 NOTORIOUS Cars...")."""
    font_size = 68
    font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
    max_width = canvas_w - 90
    words = title.upper().split()
    accent_idx = 1 if len(words) >= 2 and words[0][:1].isdigit() else None

    lines = _wrap_words(draw, words, font, max_width)
    while len(lines) > 2 and font_size > 38:
        font_size -= 5
        font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
        lines = _wrap_words(draw, words, font, max_width)

    line_height = font_size + 8
    total_height = line_height * len(lines)
    y = (TITLE_AREA_HEIGHT - total_height) // 2

    space_w = draw.textlength(" ", font=font)
    global_idx = 0
    for line_words in lines:
        line_w = draw.textlength(" ".join(line_words), font=font)
        x = (canvas_w - line_w) / 2
        for w in line_words:
            color = ACCENT_COLOR if global_idx == accent_idx else "black"
            draw.text((x, y), w, font=font, fill=color)
            x += draw.textlength(w, font=font) + space_w
            global_idx += 1
        y += line_height


def _draw_label(draw, text, cx, top, max_width, font_size=26):
    """Plain bold black label - sits on white, so no outline needed."""
    font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
    lines = _wrap_words(draw, text.upper().split(), font, max_width)
    y = top
    for line_words in lines:
        line_text = " ".join(line_words)
        w = draw.textlength(line_text, font=font)
        draw.text((cx - w / 2, y), line_text, font=font, fill="black")
        y += font_size + 4


def render_grid(item_names: list, image_paths: list, title: str):
    """
    Render the full grid image and return (canvas, cells).

    canvas: a PIL RGB Image at GRID_W x GRID_H.
    cells:  a list of dicts, one per rendered item, each:
              {"name", "cx", "cy", "x0", "y0", "x1", "y1"}
            giving the center and bounding box (in pixels) of that item's
            cell - used by the video builder to zoom into each item.

    Only fills complete rows (drops leftover items) so the grid is always a
    clean rectangle, never lopsided.
    """
    canvas = Image.new("RGB", (GRID_W, GRID_H), "white")
    draw = ImageDraw.Draw(canvas)

    _draw_title(draw, title, GRID_W)

    items = [
        (n, p) for n, p in zip(item_names, image_paths)
        if p and Path(p).exists()
    ][:MAX_GRID_ITEMS]

    cols = GRID_COLS
    if len(items) >= cols:
        # keep only complete rows
        items = items[:(len(items) // cols) * cols]
    if not items:
        raise ValueError("No usable images for the grid")

    rows = max(1, len(items) // cols) if len(items) >= cols else 1
    grid_height = GRID_H - GRID_TOP
    cell_w = GRID_W // cols
    cell_h = grid_height // rows
    circle_size = int(min(cell_w, cell_h) * 0.66)

    cells = []
    for idx, (name, img_path) in enumerate(items):
        row = idx // cols
        col = idx % cols
        cx = col * cell_w + cell_w // 2
        cy = GRID_TOP + row * cell_h + int(cell_h * 0.34)

        circle = _circle_crop(img_path, circle_size)
        canvas.paste(circle, (cx - circle_size // 2, cy - circle_size // 2), circle)
        _draw_label(draw, name, cx, cy + circle_size // 2 + 10, cell_w - 16)

        cells.append({
            "name": name,
            "cx": cx,
            "cy": cy,
            "x0": col * cell_w,
            "y0": GRID_TOP + row * cell_h,
            "x1": col * cell_w + cell_w,
            "y1": GRID_TOP + row * cell_h + cell_h,
        })

    return canvas, cells
