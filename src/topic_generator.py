"""
Stage 1: Topic generation.
Picks a new "catalog" style car topic (e.g. "12 Concept Cars That Never
Made It to Production") in the Car Professor format, avoiding topics
already used. Uses Groq's free API (https://console.groq.com) - no cost,
just a free API key stored as a GitHub secret (GROQ_API_KEY).
"""

import os
import json
import requests
from pathlib import Path

from groq_client import groq_post

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"  # Groq deprecated the llama-3.3 chat models in 2026; this is their current recommended general-purpose model
USED_TOPICS_FILE = Path(__file__).parent.parent / "data" / "used_topics.json"

TOPIC_PROMPT = """You generate YouTube video topics for "Car Professor," a channel
that teaches people about cars in 8-15 minute videos using a "catalog" format:
a numbered list of N distinct items (cars, engines, failures, records, etc.),
each with its own self-contained mini-story (what it was, what made it notable,
what happened to it).

Rules:
- Topic must be about real, factual automotive history/trivia (no fiction)
- Must fit a catalog format: "N of X" (e.g. "10 Cars Banned From Racing")
- N should be between 8 and 15
- Must NOT be any of these already-used topics: {used_topics}
- Pick something with strong visual variety (different cars/eras look different)
- Prefer topics with genuinely interesting, little-known stories

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "title": "the video title",
  "item_count": <N>,
  "theme": "one sentence describing the angle/theme"
}}
"""


def load_used_topics() -> list:
    if USED_TOPICS_FILE.exists():
        return json.loads(USED_TOPICS_FILE.read_text())
    return []


def save_used_topic(title: str):
    used = load_used_topics()
    used.append(title)
    USED_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_TOPICS_FILE.write_text(json.dumps(used, indent=2))


def generate_topic() -> dict:
    api_key = os.environ["GROQ_API_KEY"]
    used_topics = load_used_topics()

    prompt = TOPIC_PROMPT.format(used_topics=json.dumps(used_topics))

    resp = groq_post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json_body={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
        },
        timeout=60,
    )
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip accidental markdown fences if the model adds them anyway
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0]

    topic = json.loads(content)
    return topic


if __name__ == "__main__":
    topic = generate_topic()
    print(json.dumps(topic, indent=2))
