"""
Generate a batch of viral car education video topic ideas using Groq.
Run this to plan your content calendar.
"""

import os
import json
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

PROMPT = """You are a YouTube strategist for a car education channel that uses stickman animations.
The audience is everyday car owners aged 18-45 who are curious but not mechanics.

Generate 20 viral video topic ideas across these categories:
1. How car parts work (engine, transmission, brakes, suspension, etc.)
2. Car brand histories (Ferrari, Toyota, Ford, Porsche, BMW, etc.)
3. Famous car stories (the car that won Le Mans, why the VW Beetle was designed, etc.)
4. Maintenance explained simply (why oil changes matter, what the check engine light means)
5. Engineering curiosities (why do cars have spare tires, how cruise control works, etc.)

For each topic, include:
- title: clickable YouTube title
- hook: one-sentence hook for the opening of the video
- category: which category above (1-5)

Respond ONLY with valid JSON array, no markdown:
[{"title": "...", "hook": "...", "category": 1}, ...]
"""

def generate_topics(n: int = 20) -> list:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": PROMPT}],
        temperature=0.9,
        max_tokens=2000,
    )
    raw = response.choices[0].message.content.strip()
    import re
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


if __name__ == "__main__":
    print("Generating topic ideas...")
    topics = generate_topics()
    print(f"\n{'='*60}")
    print(f"🚗 {len(topics)} Car Education Video Topics")
    print(f"{'='*60}\n")
    for i, t in enumerate(topics, 1):
        print(f"{i:2}. [{t['category']}] {t['title']}")
        print(f"    Hook: {t['hook']}\n")

    with open("topic_ideas.json", "w") as f:
        json.dump(topics, f, indent=2)
    print(f"Saved to topic_ideas.json")
