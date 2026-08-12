"""
Stage 5: Video assembly.
Builds the final video using static image cuts (no zoom/pan effects):
each image displays full-frame for its share of the segment's narration,
then hard-cuts to the next. Audio-driven timing - each segment's visuals
are stretched/cut to match its voiceover duration exactly.
"""

from pathlib import Path
from PIL import Image
import numpy as np

# moviepy 1.0.3 calls PIL.Image.ANTIALIAS internally, which was removed in
# Pillow 10+ (renamed to Image.LANCZOS). Patch it back in rather than pinning
# Pillow down, since other stages rely on the modern Pillow API.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
)

W, H = 1920, 1080


def _load_rgb_clip(image_path: str) -> ImageClip:
    """
    Load an image as an ImageClip, forcing RGB. Some source photos (older
    black-and-white press photos in particular) come through as single-channel
    grayscale, which crashes moviepy's compositor when mixed with RGB clips -
    it expects every frame to have 3 color channels. Converting through PIL
    first guarantees a consistent 3-channel array regardless of the source.
    """
    img = Image.open(image_path).convert("RGB")
    return ImageClip(np.array(img))


def _cover_fit_clip(image_path: str, duration: float) -> ImageClip:
    """
    Static clip: scale the image to fully cover the WxH frame (no letterboxing,
    no distortion), center-crop any overflow, and hold it still for the full
    duration. No animation - a plain, fast-to-render still frame.
    """
    clip = _load_rgb_clip(image_path)
    img_w, img_h = clip.size
    scale = max(W / img_w, H / img_h)
    clip = clip.resize(scale)
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
    return clip.set_duration(duration)


def _build_segment_visual(image_paths: list, duration: float) -> CompositeVideoClip:
    """
    One segment's visual track: split the segment's duration evenly across
    all available images for that segment, each shown as a static still,
    hard-cut to the next. No zoom, no pan.
    """
    if not image_paths:
        raise ValueError("No images available for this segment")

    per_image = duration / len(image_paths)
    clips = [_cover_fit_clip(p, per_image) for p in image_paths]

    if len(clips) == 1:
        return clips[0]

    return concatenate_videoclips(clips, method="compose")


def build_video(segments: list, audio_results: list, images_by_segment: dict, out_path: Path):
    """
    segments: script segments (list of {name, script, image_query})
    audio_results: from tts_engine.synthesize_segments (list of {name, wav_path, duration})
    images_by_segment: {segment_index: [local image paths]}
    """
    clips = []

    for i, seg in enumerate(segments):
        audio = AudioFileClip(audio_results[i]["wav_path"])
        images = images_by_segment.get(i, [])
        visual = _build_segment_visual(images, audio.duration)
        visual = visual.set_audio(audio)
        clips.append(visual)

    # Outro: reuse the last segment's last image as a static backdrop
    outro_audio = AudioFileClip(audio_results[-1]["wav_path"])
    last_images = images_by_segment.get(len(segments) - 1, [])
    if last_images:
        outro_visual = _cover_fit_clip(last_images[0], outro_audio.duration)
        outro_visual = outro_visual.set_audio(outro_audio)
        clips.append(outro_visual)

    final = concatenate_videoclips(clips, method="compose")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_path), fps=24, codec="libx264", audio_codec="aac",
        threads=4, preset="veryfast",
    )
    return out_path


if __name__ == "__main__":
    print("Run via pipeline.py - this module needs real segments/audio/images to build a video.")
