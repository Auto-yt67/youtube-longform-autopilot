"""
Stage 5: Video assembly.
Builds the final video matching the observed formula: zoom into the primary
image while narrating, cut to supporting images partway through, zoom back
out before the next segment. Audio-driven timing - each segment's visuals
are stretched/cut to match its voiceover duration exactly.
"""

from pathlib import Path
from moviepy.editor import (
    ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
)

W, H = 1920, 1080


def _ken_burns_clip(image_path: str, duration: float, zoom_in: bool = True) -> ImageClip:
    """Create a slow zoom (Ken Burns) clip from a still image."""
    clip = ImageClip(image_path).resize(height=H * 1.15)
    clip = clip.set_position("center").set_duration(duration)

    start_scale, end_scale = (1.0, 1.12) if zoom_in else (1.12, 1.0)

    def resize_func(t):
        progress = t / duration if duration > 0 else 0
        return start_scale + (end_scale - start_scale) * progress

    clip = clip.resize(resize_func)
    return clip.set_position("center")


def _build_segment_visual(image_paths: list, duration: float) -> CompositeVideoClip:
    """
    One segment's visual track: zoom into the first (primary) image,
    cut to 1-3 supporting images partway through, zoom back out on return
    to the primary before the segment ends - matching the source formula.
    """
    if not image_paths:
        raise ValueError("No images available for this segment")

    primary = image_paths[0]
    supporting = image_paths[1:4]

    if not supporting or duration < 4:
        # Short segment or no supporting images - just one zoom-in clip
        clip = _ken_burns_clip(primary, duration, zoom_in=True)
        return clip.resize((W, H))

    # Split time: zoom-in on primary, cut through supporting images, zoom-out on primary
    intro_dur = duration * 0.3
    outro_dur = duration * 0.25
    middle_dur = duration - intro_dur - outro_dur
    per_support = middle_dur / len(supporting)

    clips = [_ken_burns_clip(primary, intro_dur, zoom_in=True)]
    for img in supporting:
        clips.append(_ken_burns_clip(img, per_support, zoom_in=True))
    clips.append(_ken_burns_clip(primary, outro_dur, zoom_in=False))

    sequence = concatenate_videoclips(clips, method="compose")
    return sequence.resize((W, H))


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
        outro_visual = _ken_burns_clip(last_images[0], outro_audio.duration, zoom_in=False)
        outro_visual = outro_visual.resize((W, H)).set_audio(outro_audio)
        clips.append(outro_visual)

    final = concatenate_videoclips(clips, method="compose")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_path), fps=30, codec="libx264", audio_codec="aac",
        threads=4, preset="medium",
    )
    return out_path


if __name__ == "__main__":
    print("Run via pipeline.py - this module needs real segments/audio/images to build a video.")
