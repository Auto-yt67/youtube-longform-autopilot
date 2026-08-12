"""
Stage 2: Script generation.
Writes the full narration script for a topic, matching the "catalog" formula:
cold open per item (no transition fluff), tight self-contained story arc,
~120-220 words per segment. Also produces an image search query per segment
for the image-sourcing stage.

The INTRO is generated separately (generate_intro) and deliberately LAST -
after top-up segments are added and after image sourcing has dropped any
segments it couldn't find licensed images for. Writing it earlier would mean
previewing cars that never appear in the finished video.
"""

import os
import json

from groq_client import groq_post

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SCRIPT_PROMPT = """Write the full narration script for a YouTube video titled:
"{title}"

Theme: {theme}
Number of items: {item_count}

Format rules (match this exactly - it's a proven formula):
- Each item gets its own segment. Start COLD with the item's name/title - no
  "next up" or "let's talk about" transitions.
- Each segment: 150-260 words. Tell a tight story - what it was, the key
  twist/event/fact that makes it notable, and what happened to it (the "fate").
- Plain, punchy, factual narration. No fluff, no rhetorical questions, no host
  opinions like "I love this one."
- All facts must be real and accurate - this is an educational channel.
- End with a short outro (2-3 sentences: ask viewers what they want to see
  next, like/subscribe).

Also provide, for EACH segment, a short "image_query" - a specific search
term (3-6 words) that would find real photos of that exact car/subject on
Wikimedia Commons.

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "title": "{title}",
  "segments": [
    {{"name": "item name", "script": "the narration text", "image_query": "search terms"}}
  ],
  "outro": "the outro narration text"
}}
"""

TOPUP_PROMPT = """You are extending an existing YouTube video script titled "{title}"
(theme: {theme}) because it's running short of the target length.

The video ALREADY covers these items - do NOT repeat any of them:
{existing_names}

Write {extra_count} MORE items in the exact same format and style:
- Start COLD with the item's name/title - no transition phrases
- Each segment: 150-260 words, same tight story structure (what it was, the
  key twist/fact, what happened to it)
- Plain, punchy, factual narration, no fluff or host opinions
- All facts must be real and accurate

Also provide an "image_query" per segment (3-6 words, for Wikimedia Commons
image search).

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "segments": [
    {{"name": "item name", "script": "the narration text", "image_query": "search terms"}}
  ]
}}
"""

INTRO_PROMPT = """Write the opening narration for a YouTube video titled "{title}"
(theme: {theme}).

This intro plays over a GRID showing all {item_count} items at once, before the
video zooms into the first one. The narration must match what's on screen.

Rules:
- 90-130 words. This is the intro only - not the first item.
- Open with a hook tied to the theme. No "welcome back to the channel," no
  "in today's video," no channel-intro cliches.
- Tell the viewer what the video covers and roughly how it's structured
  (a run through {item_count} of these, one at a time).
- You may name 2-3 of the most recognizable items below as a teaser, but do
  NOT list all of them and do NOT describe them in detail - that's what the
  rest of the video is for.
- Plain, punchy, factual. Same voice as the rest of the script.
- End on a line that leads into the first item without naming it.

The items covered, in order:
{item_names}

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "intro": "the intro narration text"
}}
"""

ACCENT_PROMPT = """Pick the single most eye-catching word from this YouTube video title:

"{title}"

This word will be printed in RED on the thumbnail while the rest stays black,
so it needs to be the word that makes someone stop scrolling.

Rules:
- Pick exactly ONE word that appears in the title, spelled exactly as it appears.
- Choose the word carrying the hook - the surprising, dramatic, or specific one.
- Do NOT pick filler words: the, that, a, an, of, and, to, in, with, from, for.
- Do NOT pick a number.

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "accent_word": "the word"
}}
"""


def _strip_fences(content: str) -> str:
    """Groq sometimes wraps JSON in markdown fences despite instructions."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]
    return content


def generate_script(topic: dict) -> dict:
    api_key = os.environ["GROQ_API_KEY"]
    prompt = SCRIPT_PROMPT.format(
        title=topic["title"], theme=topic["theme"], item_count=topic["item_count"]
    )

    resp = groq_post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json_body={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 8000,
        },
        timeout=120,
    )
    content = _strip_fences(resp.json()["choices"][0]["message"]["content"])
    script = json.loads(content)
    return script


def generate_additional_segments(topic: dict, existing_names: list, extra_count: int) -> list:
    """
    Top-up call used when the initial script comes in short of the target
    video length. Asks for more items in the same format, explicitly
    excluding anything already covered.
    """
    api_key = os.environ["GROQ_API_KEY"]
    prompt = TOPUP_PROMPT.format(
        title=topic["title"],
        theme=topic["theme"],
        existing_names="\n".join(f"- {n}" for n in existing_names),
        extra_count=extra_count,
    )

    resp = groq_post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json_body={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 4000,
        },
        timeout=90,
    )
    content = _strip_fences(resp.json()["choices"][0]["message"]["content"])
    result = json.loads(content)
    return result["segments"]


def generate_intro(topic: dict, final_names: list) -> str:
    """
    Write the intro narration that plays over the grid.

    IMPORTANT: call this LAST - after top-up segments have been added AND
    after image sourcing has dropped any segments with no licensed images.
    `final_names` must be the names that actually make it into the video,
    in the order they appear, or the intro will promise items the viewer
    never sees.

    Falls back to a generic intro if the API call fails, so a bad Groq
    response can't take down the whole run.
    """
    api_key = os.environ["GROQ_API_KEY"]
    prompt = INTRO_PROMPT.format(
        title=topic["title"],
        theme=topic["theme"],
        item_count=len(final_names),
        item_names="\n".join(f"- {n}" for n in final_names),
    )

    try:
        resp = groq_post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_body={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 1000,
            },
            timeout=60,
        )
        content = _strip_fences(resp.json()["choices"][0]["message"]["content"])
        return json.loads(content)["intro"]
    except Exception as e:
        print(f"  ! Intro generation failed ({e}) - using fallback intro")
        return (
            f"{topic['title']}. We're running through {len(final_names)} of them, "
            f"one at a time. Here's the first."
        )


_FILLER_WORDS = {
    "the", "that", "a", "an", "of", "and", "to", "in", "with", "from",
    "for", "on", "at", "by", "its", "it", "are", "is", "was", "were",
}


def _fallback_accent(title: str) -> str:
    """Longest non-filler, non-numeric word - used if the API call fails."""
    words = [w.strip(".,:!?-") for w in title.split()]
    candidates = [
        w for w in words
        if w.lower() not in _FILLER_WORDS and not w.replace(",", "").isdigit()
    ]
    return max(candidates, key=len) if candidates else (words[0] if words else "")


def pick_accent_word(title: str) -> str:
    """
    Choose the word to print in red on the thumbnail.

    Verifies the model's answer actually appears in the title - a hallucinated
    word would silently fall through to no accent at all, since the thumbnail
    matches on exact text.
    """
    api_key = os.environ["GROQ_API_KEY"]
    prompt = ACCENT_PROMPT.format(title=title)

    try:
        resp = groq_post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_body={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 100,
            },
            timeout=30,
        )
        content = _strip_fences(resp.json()["choices"][0]["message"]["content"])
        word = json.loads(content)["accent_word"].strip()

        title_words = {w.strip(".,:!?-").lower() for w in title.split()}
        if word.lower() in title_words:
            return word
        print(f"  ! Accent word '{word}' not found in title - using fallback")
    except Exception as e:
        print(f"  ! Accent word selection failed ({e}) - using fallback")

    return _fallback_accent(title)


if __name__ == "__main__":
    from topic_generator import generate_topic

    topic = generate_topic()
    script = generate_script(topic)
    names = [s["name"] for s in script["segments"]]
    script["intro"] = generate_intro(topic, names)
    print(json.dumps(script, indent=2))
    print("Accent word:", pick_accent_word(script["title"]))
