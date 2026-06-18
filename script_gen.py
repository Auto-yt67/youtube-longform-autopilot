"""
Script generation using Groq (llama-3.3-70b-versatile) - free tier
Generates a full narration script split into scenes with image prompts
"""

import os
import json
import re
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

SYSTEM_PROMPT = """You are a YouTube script writer for a car education channel.
The channel makes short, engaging educational videos using simple stickman-style animations.
Videos are 3-5 minutes long, fun and accessible for everyday car owners — not gearheads.
Topics include: how car parts work, car history, brand histories, famous cars, maintenance basics, engineering curiosities.

Your scripts must be split into clear SCENES. Each scene is ~10-20 seconds of narration paired with one illustration.

You MUST respond with ONLY valid JSON, no markdown, no preamble. Format:
{
  "title": "YouTube video title (clickbait-friendly but accurate)",
  "description": "YouTube description (2-3 paragraphs + hashtags)",
  "tags": ["tag1", "tag2", ...],
  "narration": "The FULL narration text as one continuous string (all scenes combined). Use natural pauses with commas and periods.",
  "scenes": [
    {
      "id": 1,
      "narration_excerpt": "Exact sentence(s) from the narration for this scene",
      "image_prompt": "Simple stickman illustration prompt. White background, black stickman figures, simple labeled diagrams, minimal color. Describe exactly what to show.",
      "scene_description": "Brief internal note about what this scene covers"
    }
  ]
}

Rules:
- 12-18 scenes total
- narration_excerpt must be exact substrings of the full narration field
- image_prompt: always white background, stickman art style, simple and clean
- Keep narration conversational, like you're explaining to a friend
- No jargon without explanation
"""

def generate_script(topic: str) -> dict:
    """Generate a full script for a given car topic."""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Write a script for this topic: {topic}"}
        ],
        temperature=0.7,
        max_tokens=4000,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    script = json.loads(raw)

    # Validate structure
    assert "title" in script
    assert "narration" in script
    assert "scenes" in script
    assert len(script["scenes"]) >= 5

    return script


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "How does a car engine work?"
    script = generate_script(topic)
    print(json.dumps(script, indent=2))
