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

TITLE_AREA_HEIGHT = 175
TITLE_TOP_MARGIN = 40   # push the title down from the very top edge
GRID_TOP = TITLE_AREA_HEIGHT + TITLE_TOP_MARGIN + 30  # clearance so a 2-line title never overlaps row 1
GRID_COLS = 6
ACCENT_COLOR = "#e02020"
MAX_GRID_ITEMS = 18   # up to a 6x3 grid


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
    font_size = 80  # bigger title (was 66)
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
    y = TITLE_TOP_MARGIN + (TITLE_AREA_HEIGHT - total_height) // 2

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


def _shorten_label(name: str, max_words: int = 3) -> str:
    """
    Trim a full item name down to a short label for under the circle.
    Strips parentheticals and anything after a dash/em-dash (which is usually
    a description, not the name), then caps the word count. So
    "Volvo 240 (1974) - Side Impact Protection System" -> "Volvo 240".
    """
    import re
    s = re.sub(r"\([^)]*\)", "", name)          # drop parentheticals
    s = re.split(r"\s[-\u2013\u2014]\s", s)[0]   # keep only text before " - " / " – " / " — "
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    if len(words) > max_words:
        s = " ".join(words[:max_words])
    return s or name


def _draw_label(draw, text, cx, top, max_width, font_size=30):
    font = _font(font_size)
    lines = _wrap_words(draw, text.upper().split(), font, max_width)
    y = top
    for line_words in lines:
        line_text = " ".join(line_words)
        w = draw.textlength(line_text, font=font)
        draw.text((cx - w / 2, y), line_text, font=font, fill="black")
        y += font_size + 4


def render_grid(item_names, image_paths, title, accent=False, only_index=None,
                cutout_cache=None):
    """
    Render the grid image and return (canvas, cells).

    accent:      color the word after a leading number red (thumbnail only).
    only_index:  if set, draw ONLY that cell's circle + label (all other cells
                 left as blank cream/white background). Used to build the
                 "solo" frame that the video cross-fades to while zooming in,
                 so neighboring circles dissolve away. Layout is identical to a
                 full render, so coordinates line up exactly.
    cutout_cache: optional dict {img_path: RGBA circle} to avoid rebuilding the
                 same rembg cutout twice (full grid + solo frames reuse it).
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
    fill_factor = 0.86 if rows <= 2 else 0.74
    circle_size = int(min(cell_w, cell_h) * fill_factor)

    cells = []
    for idx, (name, img_path) in enumerate(items):
        row = idx // cols
        col = idx % cols
        cx = col * cell_w + cell_w // 2
        cy = GRID_TOP + row * cell_h + int(cell_h * 0.34)

        # when rendering a solo frame, only draw the requested cell
        if only_index is None or idx == only_index:
            if cutout_cache is not None and img_path in cutout_cache:
                circle = cutout_cache[img_path]
            else:
                circle = make_circle(img_path, circle_size, cutout=True)
                if cutout_cache is not None:
                    cutout_cache[img_path] = circle
            canvas.paste(circle, (cx - circle_size // 2, cy - circle_size // 2), circle)
            _draw_label(draw, _shorten_label(name), cx, cy + circle_size // 2 + 12, cell_w - 16)

        cells.append({
            "name": name, "cx": cx, "cy": cy,
            "x0": col * cell_w, "y0": GRID_TOP + row * cell_h,
            "x1": col * cell_w + cell_w, "y1": GRID_TOP + row * cell_h + cell_h,
        })

    return canvas, cells
