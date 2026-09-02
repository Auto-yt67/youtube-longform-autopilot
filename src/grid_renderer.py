"""
Shared grid renderer.

Renders the grid of circular car cutouts with a title, used for BOTH the
thumbnail and the video's opening shot. Returns per-cell pixel coordinates so
the video builder can zoom into each item.

Circles use background-removed cutouts on off-white with a black ring
(cutout.make_circle). The title uses the bubbly Luckiest Guy display font.
The colored accent word is drawn only when accent=True - the pipeline enables
it for the thumbnail and disables it for the video's opening grid.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from cutout import make_circle

GRID_W, GRID_H = 1920, 1080

# Luckiest Guy (bubbly display font) is downloaded into src/assets/fonts by the
# GitHub Actions workflow. Fall back to DejaVu Bold if it's somehow missing.
_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
FONT_DISPLAY = str(_FONT_DIR / "LuckiestGuy-Regular.ttf")
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TITLE_AREA_HEIGHT = 150
GRID_TOP = TITLE_AREA_HEIGHT + 12
GRID_COLS = 6
ACCENT_COLOR = "#e02020"
MAX_GRID_ITEMS = 12


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DISPLAY if Path(FONT_DISPLAY).exists() else FONT_FALLBACK
    return ImageFont.truetype(path, size)


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


def _draw_title(draw, title, canvas_w, accent):
    font_size = 66
    font = _font(font_size)
    max_width = canvas_w - 90
    words = title.upper().split()
    accent_idx = 1 if (accent and len(words) >= 2 and words[0][:1].isdigit()) else None

    lines = _wrap_words(draw, words, font, max_width)
    while len(lines) > 2 and font_size > 36:
        font_size -= 5
        font = _font(font_size)
        lines = _wrap_words(draw, words, font, max_width)

    line_height = font_size + 10
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


def _draw_label(draw, text, cx, top, max_width, font_size=30):
    font = _font(font_size)
    lines = _wrap_words(draw, text.upper().split(), font, max_width)
    y = top
    for line_words in lines:
        line_text = " ".join(line_words)
        w = draw.textlength(line_text, font=font)
        draw.text((cx - w / 2, y), line_text, font=font, fill="black")
        y += font_size + 4


def render_grid(item_names, image_paths, title, accent=False):
    """
    Render the full grid image and return (canvas, cells).

    accent: color the word after a leading number red (thumbnail only). The
            video's opening grid passes accent=False.
    """
    canvas = Image.new("RGB", (GRID_W, GRID_H), "white")
    draw = ImageDraw.Draw(canvas)

    _draw_title(draw, title, GRID_W, accent)

    items = [
        (n, p) for n, p in zip(item_names, image_paths)
        if p and Path(p).exists()
    ][:MAX_GRID_ITEMS]

    cols = GRID_COLS
    if len(items) >= cols:
        items = items[:(len(items) // cols) * cols]
    if not items:
        raise ValueError("No usable images for the grid")

    rows = max(1, len(items) // cols) if len(items) >= cols else 1
    grid_height = GRID_H - GRID_TOP
    cell_w = GRID_W // cols
    cell_h = grid_height // rows
    circle_size = int(min(cell_w, cell_h) * 0.72)

    cells = []
    for idx, (name, img_path) in enumerate(items):
        row = idx // cols
        col = idx % cols
        cx = col * cell_w + cell_w // 2
        cy = GRID_TOP + row * cell_h + int(cell_h * 0.34)

        circle = make_circle(img_path, circle_size, cutout=True)
        canvas.paste(circle, (cx - circle_size // 2, cy - circle_size // 2), circle)
        _draw_label(draw, name, cx, cy + circle_size // 2 + 12, cell_w - 16)

        cells.append({
            "name": name, "cx": cx, "cy": cy,
            "x0": col * cell_w, "y0": GRID_TOP + row * cell_h,
            "x1": col * cell_w + cell_w, "y1": GRID_TOP + row * cell_h + cell_h,
        })

    return canvas, cells
