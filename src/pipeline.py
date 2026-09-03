"""
Full pipeline orchestrator. Runs every stage end to end:
  topic -> script -> images -> voiceover -> grid -> video -> thumbnail -> upload

Run this from GitHub Actions on a schedule, or locally with:
    python src/pipeline.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from topic_generator import generate_topic, save_used_topic
from script_writer import generate_script, generate_additional_segments
from image_fetcher import download_images, download_images_with_fallback
from tts_engine import synthesize_segments
from grid_renderer import render_grid, MAX_GRID_ITEMS
from video_builder import build_video
from thumbnail_generator import build_thumbnail
from youtube_upload import upload_to_youtube

WORKDIR = Path("run_output") / datetime.now().strftime("%Y%m%d_%H%M%S")

WORDS_PER_MINUTE = 180   # Edge-TTS (Eric) at 1.25x speed - much faster than Piper's ~140.
                          # Used only for the pre-TTS estimate; the real floor is measured after TTS.
TARGET_MIN_SECONDS = 8 * 60 + 20  # aim just over 8:00 so the measured result clears 8 min
MAX_TOPUP_ROUNDS = 6
SEGMENTS_PER_TOPUP = 3
MAX_SEGMENTS = 18  # matches the 6x3 grid cap (grid_renderer.MAX_GRID_ITEMS)


def _estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_MINUTE * 60


def _retitle_to_count(title: str, count: int) -> str:
    """
    Replace the leading number in a catalog title with the actual final count.
    "12 Cars That Saved Their Brands" + count=6 -> "6 Cars That Saved Their Brands".
    If the title doesn't start with a number, leave it unchanged.
    """
    import re
    m = re.match(r"^\s*(\d+)\b(.*)$", title, flags=re.DOTALL)
    if not m:
        return title
    return f"{count}{m.group(2)}"


def _total_estimated_seconds(script: dict) -> float:
    total = _estimate_seconds(script["intro"])
    total += sum(_estimate_seconds(s["script"]) for s in script["segments"])
    total += _estimate_seconds(script["outro"])
    return total


def run():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    print(f"== Working directory: {WORKDIR} ==")

    # 1. Topic
    print("\n[1/6] Generating topic...")
    topic = generate_topic()
    print(f"  Topic: {topic['title']}")

    # 2. Script
    print("\n[2/6] Writing script...")
    script = generate_script(topic)
    segments = script["segments"]
    print(f"  {len(segments)} segments written")

    estimated = _total_estimated_seconds(script)
    print(f"  Estimated runtime: {estimated / 60:.1f} min (target: {TARGET_MIN_SECONDS / 60:.1f} min)")
    rounds = 0
    while estimated < TARGET_MIN_SECONDS and rounds < MAX_TOPUP_ROUNDS and len(segments) < MAX_SEGMENTS:
        rounds += 1
        room_left = MAX_SEGMENTS - len(segments)
        request_count = min(SEGMENTS_PER_TOPUP, room_left)
        print(f"  Below target - requesting {request_count} more segments (round {rounds})...")
        existing_names = [s["name"] for s in segments]
        extra = generate_additional_segments(topic, existing_names, request_count)
        segments.extend(extra)
        script["segments"] = segments
        estimated = _total_estimated_seconds(script)
        print(f"  New estimated runtime: {estimated / 60:.1f} min ({len(segments)} segments total)")

    if len(segments) >= MAX_SEGMENTS and estimated < TARGET_MIN_SECONDS:
        print(f"  Hit the {MAX_SEGMENTS}-segment cap before reaching target - proceeding anyway.")

    (WORKDIR / "script.json").write_text(json.dumps(script, indent=2))

    # 3. Images
    print("\n[3/6] Sourcing images from Wikimedia Commons...")

    intro_dir = WORKDIR / "images" / "intro"
    try:
        intro_images = download_images(script["intro_image_query"], intro_dir, limit=4)
    except Exception as e:
        print(f"  ! unexpected failure sourcing intro images ({e}) - treating as 0 images")
        intro_images = []
    print(f"  Intro: {len(intro_images)} images")

    images_by_segment = {}
    representative_images = []
    for i, seg in enumerate(segments):
        out_dir = WORKDIR / "images" / f"seg_{i:02d}"
        try:
            paths = download_images_with_fallback(seg["image_query"], seg["name"], out_dir, limit=4)
        except Exception as e:
            print(f"  ! unexpected failure sourcing images for '{seg['name']}' ({e}) - treating as 0 images")
            paths = []
        if not paths:
            print(f"  ! No clear-license images found for '{seg['name']}' "
                  f"(query: {seg['image_query']}) - segment will be skipped")
        images_by_segment[i] = paths
        representative_images.append(paths[0] if paths else None)
        print(f"  {seg['name']}: {len(paths)} images")

    # Drop segments with zero usable images
    usable = [i for i in range(len(segments)) if images_by_segment[i]]
    if len(usable) < len(segments):
        segments = [segments[i] for i in usable]
        images_by_segment = {new_i: images_by_segment[old_i] for new_i, old_i in enumerate(usable)}
        representative_images = [representative_images[i] for i in usable]

    # NOTE: grid-row capping and title reconciliation happen AFTER the measured
    # 8-minute floor loop below (once the final car count is known), not here.

    if not intro_images and images_by_segment.get(0):
        intro_images = images_by_segment[0]

    # 4. Voiceover (with a MEASURED 8-minute floor)
    print("\n[4/6] Generating voiceover (Edge-TTS)...")
    audio_dir = WORKDIR / "audio"
    audio_results = synthesize_segments(segments, script["intro"], script["outro"], audio_dir)
    total_duration = sum(a["duration"] for a in audio_results)
    print(f"  Measured runtime: {total_duration / 60:.1f} min (floor: {TARGET_MIN_SECONDS / 60:.1f} min)")

    # If the REAL measured audio is under the floor, add more cars (with images
    # + audio) until it clears 8 min AND lands on a complete grid row (so the
    # final row-cap below never has to drop cars back under 8 min). This is the
    # true guarantee - it works off measured duration, not a word-count estimate.
    from grid_renderer import GRID_COLS

    def _needs_more():
        # keep going if under the time floor, OR if over the floor but sitting
        # on an incomplete row (round up to the next complete row)
        on_complete_row = (len(segments) % GRID_COLS == 0)
        under_floor = total_duration < TARGET_MIN_SECONDS
        return (under_floor or not on_complete_row) and len(segments) < MAX_SEGMENTS

    floor_rounds = 0
    while _needs_more() and floor_rounds < MAX_TOPUP_ROUNDS * 2:
        floor_rounds += 1
        room = MAX_SEGMENTS - len(segments)
        # add enough to reach the next complete row (or the standard batch)
        to_next_row = (GRID_COLS - (len(segments) % GRID_COLS)) % GRID_COLS
        want = min(room, max(SEGMENTS_PER_TOPUP, to_next_row) if total_duration < TARGET_MIN_SECONDS else to_next_row or SEGMENTS_PER_TOPUP)
        want = max(1, want)
        print(f"  Extending (measured {total_duration/60:.1f} min, {len(segments)} cars) - adding {want} (round {floor_rounds})...")

        extra = generate_additional_segments(topic, [s["name"] for s in segments], want)

        for seg in extra:
            idx = len(segments)
            out_dir = WORKDIR / "images" / f"seg_{idx:02d}"
            try:
                paths = download_images_with_fallback(seg["image_query"], seg["name"], out_dir, limit=4)
            except Exception as e:
                print(f"  ! image fetch failed for '{seg['name']}' ({e})")
                paths = []
            if not paths:
                print(f"  ! no images for '{seg['name']}' - skipping this added car")
                continue

            wav_path = audio_dir / f"segment_{idx:02d}.wav"
            from tts_engine import synthesize, get_wav_duration
            synthesize(seg["script"], wav_path)
            dur = get_wav_duration(wav_path)

            segments.append(seg)
            images_by_segment[idx] = paths
            representative_images.append(paths[0])
            audio_results.insert(len(audio_results) - 1,
                                 {"name": seg["name"], "wav_path": str(wav_path), "duration": dur})
            total_duration += dur

        print(f"  Measured runtime now: {total_duration / 60:.1f} min ({len(segments)} cars)")

    if total_duration < TARGET_MIN_SECONDS:
        print(f"  ! Could not reach 8 min even at the {MAX_SEGMENTS}-car cap "
              f"(got {total_duration / 60:.1f} min) - publishing anyway.")

    # The floor loop lands on a complete row already; only trim if we stopped
    # at MAX_SEGMENTS on an incomplete row (rare - would mean images kept
    # failing). Trimming here can drop under 8 min, but only when we genuinely
    # ran out of usable cars, so it's the best available outcome.
    if len(segments) >= GRID_COLS and len(segments) % GRID_COLS != 0:
        keep = (len(segments) // GRID_COLS) * GRID_COLS
        dropped_names = {s["name"] for s in segments[keep:]}
        segments = segments[:keep]
        images_by_segment = {i: images_by_segment[i] for i in range(keep)}
        representative_images = representative_images[:keep]
        audio_results = [a for a in audio_results if a["name"] not in dropped_names]
        total_duration = sum(a["duration"] for a in audio_results)

    final_count = len(segments)
    script["title"] = _retitle_to_count(script["title"], final_count)
    print(f"  Final: {final_count} cars, {total_duration / 60:.1f} min")
    print(f"  Title: {script['title']}")

    # --- Add smooth back-reference transitions, now that the car order is final ---
    print("\n[4b/6] Adding smooth transitions between cars...")
    from script_writer import add_transitions
    from tts_engine import synthesize, get_wav_duration
    before = [s["script"] for s in segments]
    segments = add_transitions(segments)

    # Re-synthesize only the segments whose opening actually changed, and update
    # their audio entries (transitions slightly change length). Intro/outro
    # audio is untouched. Keeps audio in sync with the new narration.
    name_to_audio = {a["name"]: a for a in audio_results}
    changed = 0
    for i, seg in enumerate(segments):
        if seg["script"] == before[i]:
            continue  # unchanged (e.g. the first car's clean cold open)
        changed += 1
        wav_path = audio_dir / f"segment_{i:02d}.wav"
        synthesize(seg["script"], wav_path)
        dur = get_wav_duration(wav_path)
        entry = name_to_audio.get(seg["name"])
        if entry is not None:
            entry["wav_path"] = str(wav_path)
            entry["duration"] = dur
    total_duration = sum(a["duration"] for a in audio_results)
    print(f"  Rewrote {changed} openings; runtime now {total_duration / 60:.1f} min")

    # 5. Grid + video + thumbnail
    print("\n[5/6] Rendering grid, assembling video + thumbnail...")
    # The grid uses only the items that will actually appear in it (first
    # MAX_GRID_ITEMS, complete rows). The video's zoom cells come from the same
    # render, so grid and zoom stay perfectly aligned.
    grid_names = [s["name"] for s in segments]
    grid_reps = representative_images
    # Video's opening grid: no colored accent word (accent stays on the thumbnail only).
    # Use a cutout cache so each car's rembg cutout is built once and reused for
    # the full grid AND every solo frame (keeps the extra renders cheap).
    import numpy as np
    from grid_renderer import render_grid as _render_grid
    cutout_cache = {}
    grid_canvas, cells = _render_grid(grid_names, grid_reps, script["title"],
                                      accent=False, cutout_cache=cutout_cache)
    grid_path = WORKDIR / "grid.png"
    grid_canvas.save(grid_path)

    # Render a "solo" grid per car (only that car's circle drawn) so the video
    # can cross-fade the neighbors away while zooming in. Reuses cached cutouts.
    print("  Rendering per-car solo frames for the zoom fade...")
    solo_grids = []
    for idx in range(len(cells)):
        solo_canvas, _ = _render_grid(grid_names, grid_reps, script["title"],
                                      accent=False, only_index=idx, cutout_cache=cutout_cache)
        solo_grids.append(np.array(solo_canvas.convert("RGB")))

    # Only the segments represented in the grid get a zoom target; any beyond
    # the grid cap still play with their own photos (cell=None -> no zoom).
    video_path = WORKDIR / "final_video.mp4"
    build_video(segments, audio_results, images_by_segment, str(grid_path), cells,
                video_path, solo_grids=solo_grids)

    thumb_path = WORKDIR / "thumbnail.png"
    build_thumbnail(grid_names, grid_reps, script["title"], thumb_path)
    print(f"  Video: {video_path}")
    print(f"  Thumbnail: {thumb_path}")

    # 6. Upload
    print("\n[6/6] Uploading to YouTube...")
    description = (
        f"{topic['theme']}\n\n"
        + "\n".join(f"{i+1}. {s['name']}" for i, s in enumerate(segments))
        + "\n\nAll footage sourced from Wikimedia Commons under free-use licenses."
    )
    tags = ["cars", "automotive history", "car facts", "Car Professor"]

    url = upload_to_youtube(
        video_path=str(video_path),
        title=script["title"][:100],
        description=description,
        tags=tags,
        thumbnail_path=str(thumb_path),
        publish_settings={"privacyStatus": "public", "publishAt": None},
    )

    save_used_topic(topic["title"])
    print(f"\n\u2713 Done: {url}")
    return url


if __name__ == "__main__":
    run()
