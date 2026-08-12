"""
Stage 2: Script generation.
Writes the full narration script for a topic, matching the "catalog" formula:
cold open per item (no transition fluff), tight self-contained story arc,
~120-220 words per segment. Also produces an image search query per segment
for the image-sourcing stage.
"""

import os
import json
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SCRIPT_PROMPT = """Write the full narration script for a YouTube video titled:
"{title}"

Theme: {theme}
Number of items: {item_count}

Format rules (match this exactly - it's a proven formula):
- Each item gets its own segment. Start COLD with the item's name/title - no
  "next up" or "let's talk about" transitions.
- Each segment: 120-220 words. Tell a tight story - what it was, the key
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


def generate_script(topic: dict) -> dict:
    api_key = os.environ["GROQ_API_KEY"]
    prompt = SCRIPT_PROMPT.format(
        title=topic["title"], theme=topic["theme"], item_count=topic["item_count"]
    )

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 8000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]

    script = json.loads(content)
    return script


if __name__ == "__main__":
    import sys
    from topic_generator import generate_topic

    topic = generate_topic()
    script = generate_script(topic)
    print(json.dumps(script, indent=2))
