"""
Stage 1: Topic generation.
Picks a new "catalog" style automotive topic in the Car Professor format,
avoiding topics already used. Uses Groq's free API
(https://console.groq.com) - no cost, just a free API key stored as a
GitHub secret (GROQ_API_KEY).

Topics are NOT limited to specific car models. A channel that only ever
lists famous cars runs out of road fast and competes with every other car
channel. Rotating through parts, techniques, engineering, and industry
history widens the well considerably and gives the algorithm more surfaces
to match searches against.
"""

import os
import json
import random
from pathlib import Path

from groq_client import groq_post

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # free tier model as of writing
USED_TOPICS_FILE = Path(__file__).parent.parent / "data" / "used_topics.json"

# One is picked at random per run. Without this the model gravitates back to
# "N famous cars that..." every single time, however the prompt is worded.
CATEGORIES = [
    ("Specific vehicles",
     "Individual cars, prototypes, or concepts and their stories. "
     "e.g. '10 Concept Cars That Never Reached Production'"),
    ("Parts and components",
     "How a specific part works, why it exists, what it replaced. "
     "e.g. '12 Car Parts Most Drivers Have Never Heard Of'"),
    ("Techniques and modifications",
     "Things people do to cars and why they work. "
     "e.g. '8 Ways People Add Horsepower (And What Each One Costs)'"),
    ("Engineering and physics",
     "Why cars are built the way they are. "
     "e.g. '10 Engineering Decisions That Shaped Every Modern Car'"),
    ("Industry and business history",
     "Companies, decisions, failures, rivalries. "
     "e.g. '9 Automakers That Vanished And Why'"),
    ("Racing and records",
     "Motorsport rules, records, controversies, banned technology. "
     "e.g. '10 Technologies Banned From Formula 1'"),
    ("Design and styling",
     "Why cars look the way they do across eras. "
     "e.g. '12 Design Trends That Defined The 1970s'"),
    ("Failures and recalls",
     "Things that went wrong and what changed afterwards. "
     "e.g. '8 Recalls That Rewrote Safety Law'"),
]

TOPIC_PROMPT = """You generate YouTube video topics for "Car Professor," a channel
that teaches people about cars in 8-15 minute videos using a "catalog" format:
a numbered list of N distinct items, each with its own self-contained
mini-story.

For THIS video, use this category:
  {category_name} - {category_desc}

Rules:
- Topic must be real and factual (no fiction, no speculation)
- Must fit a catalog format: "N of X"
- N should be between 8 and 15
- Must NOT be any of these already-used topics: {used_topics}
- Every item must be something that can be PHOTOGRAPHED as a distinct
  physical object or scene. A viewer sees a picture of each item, so avoid
  abstract items that would have no clear image.
- Items should look visually different from each other
- Prefer genuinely interesting, little-known material over the obvious

Respond with ONLY valid JSON, no markdown fences, no preamble:
{{
  "title": "the video title",
  "item_count": <N>,
  "theme": "one sentence describing the angle/theme",
  "category": "{category_name}"
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


def _recent_categories(used: list, n: int = 3) -> list:
    """Category names are stored inline in used_topics entries, if present."""
    return [t.split("|", 1)[0] for t in used[-n:] if "|" in t]


def generate_topic() -> dict:
    api_key = os.environ["GROQ_API_KEY"]
    used_topics = load_used_topics()

    # Avoid repeating the last few categories so the channel doesn't run
    # three parts videos in a row by chance.
    recent = _recent_categories(used_topics)
    pool = [c for c in CATEGORIES if c[0] not in recent] or CATEGORIES
    category_name, category_desc = random.choice(pool)
    print(f"  Category: {category_name}")

    prompt = TOPIC_PROMPT.format(
        category_name=category_name,
        category_desc=category_desc,
        used_topics=json.dumps([t.split("|", 1)[-1] for t in used_topics]),
    )

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
    topic.setdefault("category", category_name)
    return topic


if __name__ == "__main__":
    topic = generate_topic()
    print(json.dumps(topic, indent=2))
