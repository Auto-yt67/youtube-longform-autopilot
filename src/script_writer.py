"""
Stage 2: Script generation.
Writes the full narration script for a topic, matching the "catalog" formula:
cold open per item (no transition fluff), tight self-contained story arc,
~150-260 words per segment. Also produces an image search query per segment
for the image-sourcing stage.
"""

import os
import json

from groq_client import groq_post

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"  # Groq deprecated the llama-3.3 chat models in 2026; this is their current recommended general-purpose model

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
            "max_tokens": 6000,  # Groq's free tier caps gpt-oss-120b at 8,000 TPM total
                                  # (input+output combined) - 6000 leaves headroom for the
                                  # prompt itself and stays safely under that ceiling
        },
        timeout=120,
    )
    content = resp.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]

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
    content = resp.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]

    result = json.loads(content)
    return result["segments"]


if __name__ == "__main__":
    import sys
    from topic_generator import generate_topic

    topic = generate_topic()
    script = generate_script(topic)
    print(json.dumps(script, indent=2))
