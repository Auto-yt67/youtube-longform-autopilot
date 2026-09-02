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
                          zoom_out: bool = False) -> VideoClip:
    """
    Zoom from the full grid frame into a single cell's region over `duration`.
    Works by cropping a window that interpolates from the whole frame to a
    tight box around the cell, then scaling that window back up to WxH.
    If zoom_out=True, plays the same motion in reverse (cell -> full grid).
    """
    gh, gw, _ = grid_img.shape

    # Target window: a padded box around the cell, matching the frame's aspect
    # ratio so the scaled-up result fills the frame without distortion.
    cx = (cell["x0"] + cell["x1"]) / 2
    cy = (cell["y0"] + cell["y1"]) / 2
    # target window height ~ 46% of the frame - close enough to fill with the
    # circle + label but not so tight it clips them
    target_h = gh * 0.46
    target_w = target_h * (W / H)

    # Keep the target window inside the image bounds
    tx0 = max(0, min(cx - target_w / 2, gw - target_w))
    ty0 = max(0, min(cy - target_h / 2, gh - target_h))

    full_w, full_h = float(gw), float(gh)
    fx0, fy0 = 0.0, 0.0

    def make_frame(t):
        prog = t / duration if duration > 0 else 1.0
        prog = max(0.0, min(1.0, prog))
        if zoom_out:
            prog = 1.0 - prog
        # ease-in-out for a less mechanical motion
        prog = prog * prog * (3 - 2 * prog)

        win_w = full_w + (target_w - full_w) * prog
        win_h = full_h + (target_h - full_h) * prog
        win_x = fx0 + (tx0 - fx0) * prog
        win_y = fy0 + (ty0 - fy0) * prog

        x0 = int(round(win_x)); y0 = int(round(win_y))
        x1 = int(round(win_x + win_w)); y1 = int(round(win_y + win_h))
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(gw, max(x1, x0 + 2)); y1 = min(gh, max(y1, y0 + 2))

        window = grid_img[y0:y1, x0:x1]
        # scale window back up to full frame
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


def build_video(segments, audio_results, images_by_segment, grid_image_path, cells, out_path):
    """
    segments:          list of {name, script, image_query}
    audio_results:     intro first, then one per segment, then outro last
                       (list of {name, wav_path, duration})
    images_by_segment: {segment_index: [local image paths]}
    grid_image_path:   path to the rendered full grid PNG (from grid_renderer)
    cells:             per-cell coordinates from grid_renderer.render_grid

    Motion per item: zoom IN from the full grid into the item's cell, hold on
    the item's photos, then zoom OUT back to the full grid - so each car gets a
    clean "zoom out of this one, zoom into the next" transition.
    """
    grid_img = _load_rgb_array(grid_image_path)
    clips = []

    PAUSE_AFTER_INTRO = 1.0  # brief beat on the grid before the first car
    ZOOM_IN_DUR = 0.9
    ZOOM_OUT_DUR = 0.7

    # --- Intro: hold on the full grid while the intro narration plays ---
    intro_audio = AudioFileClip(audio_results[0]["wav_path"])
    intro_clip = _cover_fit_clip(grid_image_path, intro_audio.duration).set_audio(intro_audio)
    clips.append(intro_clip)

    # --- Brief silent pause on the grid after the intro ("...let's get into it" [beat]) ---
    clips.append(_hold_grid_clip(grid_image_path, PAUSE_AFTER_INTRO))

    # --- Each segment: zoom in -> photos -> zoom out ---
    for i, seg in enumerate(segments):
        audio = AudioFileClip(audio_results[i + 1]["wav_path"])
        seg_dur = audio.duration
        photos = images_by_segment.get(i, [])
        cell = cells[i] if i < len(cells) else None

        if cell:
            # carve zoom-in and zoom-out from the segment's own duration,
            # scaling them down for very short segments so photos still show
            zin = min(ZOOM_IN_DUR, seg_dur * 0.22)
            zout = min(ZOOM_OUT_DUR, seg_dur * 0.18)
            photos_dur = max(0.1, seg_dur - zin - zout)

            parts = [_zoom_into_cell_clip(grid_img, cell, zin, zoom_out=False)]
            photos_clip = _segment_photos_clip(photos, photos_dur)
            if photos_clip is not None:
                parts.append(photos_clip)
            else:
                # no photos - hold the zoomed-in cell during the middle
                parts.append(_zoom_into_cell_clip(grid_img, cell, photos_dur, zoom_out=False)
                             .set_duration(photos_dur))
            parts.append(_zoom_into_cell_clip(grid_img, cell, zout, zoom_out=True))
        else:
            # segment with no grid cell (shouldn't happen after reconciliation,
            # but safe) - just show its photos full-frame
            photos_clip = _segment_photos_clip(photos, seg_dur)
            parts = [photos_clip] if photos_clip is not None else [
                _cover_fit_clip(grid_image_path, seg_dur)
            ]

        seg_visual = concatenate_videoclips(parts, method="compose") if len(parts) > 1 else parts[0]
        seg_visual = seg_visual.set_duration(seg_dur).set_audio(audio)
        clips.append(seg_visual)

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
