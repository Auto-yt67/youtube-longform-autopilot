"""
Stage 2: Script generation.
Writes the full narration script for a topic, matching the "catalog" formula:
a short intro, then a cold-open self-contained story per item.
"""

import os
import json

from groq_client import groq_post

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"  # Groq deprecated the llama-3.3 chat models in 2026

SCRIPT_PROMPT = """Write the full narration script for a YouTube video titled:
"{title}"

Theme: {theme}
Number of items: {item_count}

Format rules (match this exactly - it's a proven formula):
- Open with a short INTRO (2-4 sentences): hook the viewer on the theme and
  briefly preview what the video covers, in plain factual language - no
  "welcome back to the channel," no host chatter, no rhetorical questions.
  End the intro with a short transition line like "Let's get into it." or
  "Let's get started." as its final sentence.
- After the intro, each item gets its own segment. Start COLD with the item's
  name/title - no "next up" or "let's talk about" transitions.
- Each segment: 150-260 words. Tell a tight story - what it was, the key
  twist/event/fact that makes it notable, and what happened to it (the "fate").
- Plain, punchy, factual narration. No fluff, no rhetorical questions, no host
  opinions like "I love this one."
- All facts must be real and accurate - this is an educational channel.
- End with a short outro (2-3 sentences: ask viewers what they want to see
  next, like/subscribe).

Also provide an "intro_image_query" (3-6 words) for a general establishing
visual - and, for EACH segment, a short "image_query" (3-6 words) that would
find real photos of that exact car/subject on Wikimedia Commons.

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "title": "{title}",
  "intro": "the intro narration text",
  "intro_image_query": "search terms",
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
- Each segment: 150-260 words, same tight story structure
- Plain, punchy, factual narration, no fluff or host opinions
- All facts must be real and accurate

Also provide an "image_query" per segment (3-6 words, for Wikimedia Commons).

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "segments": [
    {{"name": "item name", "script": "the narration text", "image_query": "search terms"}}
  ]
}}
"""


def _extract_json(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]
    return content.strip()


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
            "max_tokens": 7000,
            "reasoning_effort": "low",  # gpt-oss-120b reasons by default and can burn the
                                          # whole budget on chain-of-thought, returning empty content
        },
        timeout=120,
    )
    content = _extract_json(resp.json()["choices"][0]["message"]["content"])
    if not content:
        raise ValueError(
            "Groq returned an empty response for script generation - likely spent the "
            "token budget on reasoning. Try raising max_tokens or lowering reasoning_effort."
        )
    return json.loads(content)


def generate_additional_segments(topic: dict, existing_names: list, extra_count: int) -> list:
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
            "reasoning_effort": "low",
        },
        timeout=90,
    )
    content = _extract_json(resp.json()["choices"][0]["message"]["content"])
    if not content:
        raise ValueError(
            "Groq returned an empty response for the top-up call - likely spent the token "
            "budget on reasoning. Try raising max_tokens or lowering reasoning_effort."
        )
    return json.loads(content)["segments"]


TRANSITIONS_PROMPT = """You are adding smooth spoken transitions to a car video script.
Below is the FINAL ordered list of cars, each with its narration. Rewrite the
OPENING of each segment (after the first) so it flows naturally from the
previous car - a short spoken back-reference like "Unlike the [previous car] we
just saw, this next one...", "While the [previous car] focused on X, this
one...", or "Following the [previous car], this next car took a different
path...".

Rules:
- The FIRST car keeps a clean cold open (no back-reference - nothing precedes it).
- Every other car opens with a smooth 1-sentence transition that references the
  PREVIOUS car by name, then continues into that car's own story.
- Keep the rest of each segment's facts intact - only rework the opening so it
  connects. Do not add new false facts. Do not repeat the whole previous story.
- Keep each segment about the same length as before.
- Vary the transition wording - don't start every one the same way.

The cars in order:
{car_list}

Respond with ONLY valid JSON, no markdown fences, no preamble - a list of the
rewritten narration texts in the SAME order:
{{
  "scripts": ["rewritten narration for car 1", "rewritten narration for car 2", ...]
}}
"""


def add_transitions(segments: list) -> list:
    """
    Given the FINAL ordered list of segments, rewrite each segment's opening
    (except the first) to smoothly reference the previous car by name. Returns
    the segments with updated 'script' fields. Runs as ONE pass after the car
    list is locked, so back-references always point at the real preceding car
    even after drops/top-ups/reordering.

    Falls back to the original cold-open scripts if the rewrite fails, so a bad
    transitions call never breaks the pipeline.
    """
    if len(segments) < 2:
        return segments

    car_list = "\n".join(
        f"{i+1}. {s['name']}: {s['script']}" for i, s in enumerate(segments)
    )
    prompt = TRANSITIONS_PROMPT.format(car_list=car_list)

    try:
        api_key = os.environ["GROQ_API_KEY"]
        resp = groq_post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_body={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 7000,
                "reasoning_effort": "low",
            },
            timeout=150,
        )
        content = _extract_json(resp.json()["choices"][0]["message"]["content"])
        if not content:
            raise ValueError("empty transitions response")
        new_scripts = json.loads(content)["scripts"]
        if len(new_scripts) != len(segments):
            raise ValueError(f"got {len(new_scripts)} scripts for {len(segments)} cars")
    except Exception as e:
        print(f"  ! transition rewrite failed ({e}) - keeping cold-open scripts")
        return segments

    for seg, new_text in zip(segments, new_scripts):
        if isinstance(new_text, str) and new_text.strip():
            seg["script"] = new_text.strip()
    return segments


if __name__ == "__main__":
    from topic_generator import generate_topic
    topic = generate_topic()
    print(json.dumps(generate_script(topic), indent=2))
