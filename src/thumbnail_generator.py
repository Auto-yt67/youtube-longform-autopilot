"""
Stage 5b: Thumbnail generation.
Builds a grid-of-circles thumbnail matching the reference style: a title
banner with a colored accent word, a tight 6-column x 2-row grid of circular
photos below (always a full rectangle - extra items are dropped rather than
leaving a lopsided partial row), plain bold black labels under each photo.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

THUMB_W, THUMB_H = 1280, 720
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # present on Ubuntu runners

TITLE_AREA_HEIGHT = 100  # reserved band at the top for the title text
GRID_TOP = TITLE_AREA_HEIGHT + 8
GRID_COLS = 6
ACCENT_COLOR = "#e02020"


def _circle_crop(img_path: str, size: int) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(img, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0), mask)
    return out


def _wrap_words(draw: ImageDraw.Draw, words: list, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """Greedy word-wrap that returns lists of words per line (not joined strings),
    so the caller can still color individual words after wrapping."""
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


def _draw_title(draw: ImageDraw.Draw, title: str, canvas_w: int) -> None:
    """
    Bold uppercase title, centered, wrapped to fit within the reserved top
    band. If the title leads with a number (e.g. "12 Forgotten Concept
    Cars..."), the word right after the number is colored as an accent
    (matching the reference style's "21 NOTORIOUS Racing Cars...").
    """
    font_size = 46
    font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
    max_width = canvas_w - 60
    words = title.upper().split()
    accent_idx = 1 if len(words) >= 2 and words[0][:1].isdigit() else None

    lines = _wrap_words(draw, words, font, max_width)
    while len(lines) > 2 and font_size > 26:
        font_size -= 4
        font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
        lines = _wrap_words(draw, words, font, max_width)

    line_height = font_size + 6
    total_height = line_height * len(lines)
    y = (TITLE_AREA_HEIGHT - total_height) // 2

    space_w = draw.textlength(" ", font=font)
    global_idx = 0
    for line_words in lines:
        line_text = " ".join(line_words)
        line_w = draw.textlength(line_text, font=font)
        x = (canvas_w - line_w) / 2
        for w in line_words:
            color = ACCENT_COLOR if global_idx == accent_idx else "black"
            draw.text((x, y), w, font=font, fill=color)
            x += draw.textlength(w, font=font) + space_w
            global_idx += 1
        y += line_height


def _label(draw: ImageDraw.Draw, text: str, cx: int, top: int, max_width: int, font_size: int = 20):
    """Plain bold black label - no outline needed since it sits on white, not a photo."""
    font = ImageFont.truetype(FONT_PATH_BOLD, font_size)
    lines = _wrap_words(draw, text.upper().split(), font, max_width)

    y = top
    for line_words in lines:
        line_text = " ".join(line_words)
        w = draw.textlength(line_text, font=font)
        x = cx - w / 2
        draw.text((x, y), line_text, font=font, fill="black")
        y += font_size + 3


def build_thumbnail(item_names: list, image_paths: list, title: str, out_path: Path, max_items: int = 12):
    """
    item_names: list of segment names (e.g. car names)
    image_paths: matching list of one representative image path per item

    Always renders a complete cols x rows rectangle - if the available items
    don't fill an even number of rows, the leftover items are dropped rather
    than leaving a lopsided partial row.
    """
    canvas = Image.new("RGB", (THUMB_W, THUMB_H), "white")
    draw = ImageDraw.Draw(canvas)

    _draw_title(draw, title, THUMB_W)

    items = list(zip(item_names, image_paths))[:max_items]
    items = [it for it in items if it[1] and Path(it[1]).exists()]

    cols = GRID_COLS
    full_rows_count = (len(items) // cols) * cols
    if full_rows_count == 0:
        # Fewer items than one row needs - show them all rather than nothing
        full_rows_count = len(items)
    items = items[:full_rows_count]

    if not items:
        raise ValueError("No usable images for the thumbnail")

    rows = len(items) // cols if len(items) >= cols else 1
    grid_height = THUMB_H - GRID_TOP
    cell_w = THUMB_W // cols
    cell_h = grid_height // rows
    circle_size = int(min(cell_w, cell_h) * 0.72)

    for idx, (name, img_path) in enumerate(items):
        row = idx // cols
        col = idx % cols
        cx = col * cell_w + cell_w // 2
        cy = GRID_TOP + row * cell_h + int(cell_h * 0.32)

        circle = _circle_crop(img_path, circle_size)
        canvas.paste(circle, (cx - circle_size // 2, cy - circle_size // 2), circle)

        _label(draw, name, cx, cy + circle_size // 2 + 6, cell_w - 12)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
    return out_path
