"""
Stage 5: Video assembly.

Implements the "catalog" format from the reference video:
  1. Open on the full grid (same image as the thumbnail), held during the
     intro narration.
  2. For each item, zoom from the full grid into that item's cell while its
     segment narration plays, showing that item's photos.
  3. Zoom back out to the grid briefly at the end.

The zoom is done by cropping a shrinking window out of the static grid image
and scaling it back to full frame - a smooth Ken-Burns-style push into each
cell, matching the reference's "zoom into each one, then out" motion.
"""

from pathlib import Path
from PIL import Image
import numpy as np

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, VideoClip
)

W, H = 1920, 1080


def _load_rgb_array(image_path: str) -> np.ndarray:
    return np.array(Image.open(image_path).convert("RGB"))


def _cover_fit_clip(image_path: str, duration: float) -> ImageClip:
    """Static full-frame clip - scale to cover WxH, center-crop overflow."""
    arr = _load_rgb_array(image_path)
    clip = ImageClip(arr)
    img_w, img_h = clip.size
    scale = max(W / img_w, H / img_h)
    clip = clip.resize(scale)
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
    return clip.set_duration(duration)


def _zoom_into_cell_clip(grid_img: np.ndarray, cell: dict, duration: float,
                          zoom_out: bool = False, solo_img: np.ndarray = None) -> VideoClip:
    """
    Zoom from the full grid frame into a single cell's region over `duration`.
    Works by cropping a window that interpolates from the whole frame to a
    tight box around the cell, then scaling that window back up to WxH.
    If zoom_out=True, plays the same motion in reverse (cell -> full grid).

    If solo_img is given (a grid frame with ONLY this cell's circle drawn), the
    zoom cross-fades from the full grid to the solo frame as it pushes in, so
    the neighboring circles dissolve away and you land on a clean isolated car.
    """
    gh, gw, _ = grid_img.shape

    cx = (cell["x0"] + cell["x1"]) / 2
    cy = (cell["y0"] + cell["y1"]) / 2
    target_h = gh * 0.46
    target_w = target_h * (W / H)

    # Center the final window ON the circle - do NOT clamp it inside the image.
    # For edge/corner cells this means the window can extend past the image
    # border; those out-of-bounds areas are padded with the grid's white
    # background so the circle always lands dead-center on screen.
    tx0 = cx - target_w / 2
    ty0 = cy - target_h / 2

    full_w, full_h = float(gw), float(gh)
    # the fully-zoomed-out window is the whole image, centered
    fx0, fy0 = 0.0, 0.0

    def _crop_padded(src, wx, wy, ww, wh):
        """Crop a (wx,wy,ww,wh) window from src, padding out-of-bounds areas
        with white so the window can extend past the image edge."""
        x0 = int(round(wx)); y0 = int(round(wy))
        x1 = int(round(wx + ww)); y1 = int(round(wy + wh))
        out_w = max(2, x1 - x0); out_h = max(2, y1 - y0)
        canvas = np.full((out_h, out_w, 3), 255, dtype=np.uint8)  # white pad
        # region of the source that actually overlaps the window
        sx0 = max(0, x0); sy0 = max(0, y0)
        sx1 = min(gw, x1); sy1 = min(gh, y1)
        if sx1 > sx0 and sy1 > sy0:
            dx0 = sx0 - x0; dy0 = sy0 - y0
            canvas[dy0:dy0 + (sy1 - sy0), dx0:dx0 + (sx1 - sx0)] = src[sy0:sy1, sx0:sx1]
        return canvas

    def make_frame(t):
        prog = t / duration if duration > 0 else 1.0
        prog = max(0.0, min(1.0, prog))
        if zoom_out:
            prog = 1.0 - prog
        prog = prog * prog * (3 - 2 * prog)  # ease-in-out

        win_w = full_w + (target_w - full_w) * prog
        win_h = full_h + (target_h - full_h) * prog
        win_x = fx0 + (tx0 - fx0) * prog
        win_y = fy0 + (ty0 - fy0) * prog

        window = _crop_padded(grid_img, win_x, win_y, win_w, win_h)

        if solo_img is not None:
            solo_window = _crop_padded(solo_img, win_x, win_y, win_w, win_h)
            fade = min(1.0, prog / 0.7)  # neighbors gone by ~70% in
            window = (window.astype(np.float32) * (1 - fade)
                      + solo_window.astype(np.float32) * fade).astype(np.uint8)

        pil = Image.fromarray(window).resize((W, H), Image.LANCZOS)
        return np.array(pil)

    return VideoClip(make_frame, duration=duration)


def _segment_photos_clip(image_paths: list, duration: float):
    """The item's own photos, shown full-frame, splitting the segment time."""
    if not image_paths:
        return None
    per = duration / len(image_paths)
    clips = [_cover_fit_clip(p, per) for p in image_paths]
    if len(clips) == 1:
        return clips[0]
    return concatenate_videoclips(clips, method="compose")


def _hold_grid_clip(grid_image_path, duration):
    """Static full-grid frame for a given duration (used for the post-intro pause)."""
    return _cover_fit_clip(grid_image_path, duration)


def _hold_cell_clip(grid_img, cell, duration):
    """
    Static frame of the fully-zoomed-in cell, held for `duration`. Used as a
    brief beat between the zoom-in and the zoom-out so the transition doesn't
    feel rushed. Implemented as a zoom clip frozen at its end (fully zoomed in).
    """
    frozen = _zoom_into_cell_clip(grid_img, cell, 0.001, zoom_out=False)
    last = frozen.get_frame(0.001)
    from moviepy.editor import ImageClip
    return ImageClip(last).set_duration(duration)


def build_video(segments, audio_results, images_by_segment, grid_image_path, cells,
                out_path, solo_grids=None):
    """
    segments:          list of {name, script, image_query}
    audio_results:     intro first, then one per segment, then outro last
    images_by_segment: {segment_index: [local image paths]}
    grid_image_path:   path to the rendered full grid PNG
    cells:             per-cell coordinates from grid_renderer.render_grid
    solo_grids:        optional list of numpy arrays, one per cell - each a grid
                       frame with ONLY that cell's circle drawn. When present,
                       the zoom-in cross-fades full -> solo so neighboring
                       circles dissolve away.
    """
    grid_img = _load_rgb_array(grid_image_path)
    clips = []

    PAUSE_AFTER_INTRO = 1.0    # beat on the grid before the first car
    PAUSE_BETWEEN_CARS = 0.7   # beat on the full grid between one car and the next
    PAUSE_AFTER_EXPLAIN = 0.5  # SILENT beat on the car after the narration finishes,
                                # before the transition/zoom-out (lets it breathe)
    ZOOM_IN_DUR = 0.9
    ZOOM_OUT_DUR = 0.7
    HOLD_AFTER_ZOOMIN = 0.6    # beat once zoomed into the car (before photos)
    HOLD_BEFORE_ZOOMOUT = 0.5 # beat on the zoomed-in circle before pulling back out

    # --- Intro: hold on the full grid while the intro narration plays ---
    intro_audio = AudioFileClip(audio_results[0]["wav_path"])
    intro_clip = _cover_fit_clip(grid_image_path, intro_audio.duration).set_audio(intro_audio)
    clips.append(intro_clip)

    # --- Brief silent pause on the grid after the intro ("...let's get into it" [beat]) ---
    clips.append(_hold_grid_clip(grid_image_path, PAUSE_AFTER_INTRO))

    # --- Each segment: zoom in (neighbors fade) -> hold -> photos -> hold -> zoom out ---
    for i, seg in enumerate(segments):
        audio = AudioFileClip(audio_results[i + 1]["wav_path"])
        seg_dur = audio.duration
        photos = images_by_segment.get(i, [])
        cell = cells[i] if i < len(cells) else None
        solo = solo_grids[i] if (solo_grids and i < len(solo_grids)) else None

        if cell:
            # --- narrated portion: sized to the audio, carries the voice ---
            zin = min(ZOOM_IN_DUR, seg_dur * 0.18)
            hold_in = min(HOLD_AFTER_ZOOMIN, seg_dur * 0.09)
            hold_out = min(HOLD_BEFORE_ZOOMOUT, seg_dur * 0.09)
            photos_dur = max(0.1, seg_dur - zin - hold_in - hold_out)

            narrated_parts = [
                _zoom_into_cell_clip(grid_img, cell, zin, zoom_out=False, solo_img=solo),
                _hold_cell_clip(solo if solo is not None else grid_img, cell, hold_in),
            ]
            photos_clip = _segment_photos_clip(photos, photos_dur)
            if photos_clip is not None:
                narrated_parts.append(photos_clip)
            else:
                narrated_parts.append(_hold_cell_clip(solo if solo is not None else grid_img, cell, photos_dur))
            narrated_parts.append(_hold_cell_clip(solo if solo is not None else grid_img, cell, hold_out))

            narrated = concatenate_videoclips(narrated_parts, method="compose")
            narrated = narrated.set_duration(seg_dur).set_audio(audio)
            clips.append(narrated)

            # --- SILENT pause on the car after the voice finishes explaining ---
            clips.append(_hold_cell_clip(solo if solo is not None else grid_img, cell, PAUSE_AFTER_EXPLAIN))

            # --- zoom back out (silent), neighbors fade in ---
            zout = min(ZOOM_OUT_DUR, seg_dur * 0.14)
            clips.append(_zoom_into_cell_clip(grid_img, cell, zout, zoom_out=True, solo_img=solo))
        else:
            photos_clip = _segment_photos_clip(photos, seg_dur)
            seg_visual = photos_clip if photos_clip is not None else _cover_fit_clip(grid_image_path, seg_dur)
            seg_visual = seg_visual.set_duration(seg_dur).set_audio(audio)
            clips.append(seg_visual)

        # brief silent beat on the full grid between cars (not after the last one,
        # which flows straight into the outro)
        if i < len(segments) - 1:
            clips.append(_hold_grid_clip(grid_image_path, PAUSE_BETWEEN_CARS))

    # --- Outro: hold on the full grid ---
    outro_audio = AudioFileClip(audio_results[-1]["wav_path"])
    outro_visual = _cover_fit_clip(grid_image_path, outro_audio.duration).set_audio(outro_audio)
    clips.append(outro_visual)

    final = concatenate_videoclips(clips, method="compose")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_path), fps=24, codec="libx264", audio_codec="aac",
        threads=4, preset="veryfast",
    )
    return out_path


if __name__ == "__main__":
    print("Run via pipeline.py - needs real segments/audio/images/grid to build.")
