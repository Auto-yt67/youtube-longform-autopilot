"""
Script generation using Groq (llama-3.3-70b-versatile)
Supports 5 content formulas, rotates daily, tracks used topics.
"""

import os
import json
import re
import random
from datetime import datetime
from pathlib import Path
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

FORMULAS = {
    "grid_explainer": {
        "name": "Grid Explainer",
        "description": "Every X Explained — show all items in a visual grid, then explain each one",
        "min_scenes": 20,
        "min_words": 1100,  # ~8 min at ~140 wpm
        "title_formulas": [
            "Every {topic} Explained in {N} Minutes",
            "Every Type of {topic} & How They Work",
            "All {N} {topic} Explained (You Need to Know These)",
        ],
        "topics": [
            "Car Engine Type", "Car Transmission Type", "Car Suspension Type",
            "Car Brake System", "Car Fuel Type", "Car Drive System (FWD, RWD, AWD)",
            "Car Safety Feature", "Car Sensor", "Car Light Type",
            "Car Tire Type", "Car Battery Type", "Car Exhaust System Type",
            "Supercar Brand", "Car Dashboard Warning Light",
            "Car Cooling System Type", "Car Steering System Type",
        ]
    },
    "how_it_works": {
        "name": "How It Works",
        "description": "Deep dive on one car part or system with stickman diagrams",
        "min_scenes": 15,
        "min_words": 750,  # ~5-6 min at ~140 wpm
        "title_formulas": [
            "How Does a {topic} Actually Work?",
            "The {topic} Explained Simply",
            "Why Your Car's {topic} Is More Clever Than You Think",
            "What Actually Happens When You {action} (The {topic} Explained)",
        ],
        "topics": [
            "Car Engine", "Turbocharger", "Transmission", "Differential",
            "Braking System", "Suspension", "Power Steering", "Alternator",
            "Catalytic Converter", "Fuel Injector", "Timing Belt", "Clutch",
            "Air Conditioning System", "Radiator", "Spark Plug", "Carburetor",
            "Anti-lock Braking System (ABS)", "Traction Control System",
            "CVT Transmission", "Dual Clutch Transmission",
        ]
    },
    "car_history": {
        "name": "Car History",
        "description": "Story of how cars or a car concept evolved over time",
        "min_scenes": 18,
        "min_words": 850,  # ~6 min at ~140 wpm
        "title_formulas": [
            "The History of {topic} (Nobody Tells You This)",
            "How {topic} Changed Everything",
            "The Insane History of {topic}",
            "From 0 to {result}: The Story of {topic}",
        ],
        "topics": [
            "the Car", "the Sports Car", "Electric Vehicles", "the SUV",
            "Formula 1 Racing", "the Pickup Truck", "Car Safety",
            "the Muscle Car", "Self-Driving Cars", "Car Design",
            "the Station Wagon", "the Minivan", "Road Trips",
            "Car Manufacturing", "the Supercar", "Car Engines",
        ]
    },
    "brand_history": {
        "name": "Brand History",
        "description": "Origin story and history of one car brand",
        "min_scenes": 20,
        "min_words": 1000,  # ~7 min at ~140 wpm
        "title_formulas": [
            "The Insane Story of How {brand} Started",
            "How {brand} Went From {start} to {end}",
            "The Rise (and Fall?) of {brand}",
            "Why {brand} Makes Cars the Way They Do",
        ],
        "topics": [
            "Ferrari", "Porsche", "Toyota", "Ford", "BMW",
            "Mercedes-Benz", "Volkswagen", "Lamborghini", "Bugatti",
            "Tesla", "Honda", "Chevrolet", "Dodge", "Audi",
            "McLaren", "Rolls-Royce", "Jeep", "Land Rover", "Subaru", "Mazda",
        ]
    },
    "part_history": {
        "name": "Part History",
        "description": "How a specific car part was invented and evolved",
        "min_scenes": 15,
        "min_words": 750,  # ~5-6 min at ~140 wpm
        "title_formulas": [
            "Who Invented the {part}? (The Answer Is Surprising)",
            "The History of the {part} — From {old} to {new}",
            "How the {part} Went From {old} to {new}",
            "The {part}: A History Nobody Talks About",
        ],
        "topics": [
            "Seatbelt", "Airbag", "Windshield Wiper", "Car Radio",
            "GPS Navigation", "Rearview Mirror", "Headlight",
            "Steering Wheel", "Gear Shift", "Car Horn",
            "Speedometer", "Fuel Gauge", "Cruise Control",
            "Power Windows", "Car Air Conditioning", "Turbocharger",
        ]
    }
}

SYSTEM_PROMPTS = {
    "grid_explainer": """You are a YouTube script writer for a car education channel using stickman animations.
FORMAT: Grid Explainer — like "Every Drug Explained" videos. 
Structure:
1. Hook (10s): "Today we're covering every [X] and what makes each one different"
2. Quick grid overview scene: show all items labeled in a grid
3. For each item: 2-3 scenes explaining it simply
4. Closing scene: ranking/summary

TONE: Fast-paced, punchy, surprising facts. Like a friendly car nerd explaining to a friend.
LENGTH: 8-12 minutes worth of content (20-30 scenes total)
""",
    "how_it_works": """You are a YouTube script writer for a car education channel using stickman animations.
FORMAT: How It Works — deep dive on one car system.
Structure:
1. Hook (10s): surprising fact or question about the topic
2. Simple overview of what it does
3. Step-by-step breakdown with stickman diagrams
4. Common problems/failures and why they happen
5. Interesting facts most people don't know
6. Summary

TONE: Curious, clear, like a teacher who actually makes it interesting.
LENGTH: 5-8 minutes (15-20 scenes)
""",
    "car_history": """You are a YouTube script writer for a car education channel using stickman animations.
FORMAT: Car History — storytelling format.
Structure:
1. Hook: dramatic moment from the history
2. The beginning / origin
3. Key turning points (3-4 major moments)
4. How it changed everything
5. Where it stands today
6. Surprising fact to close

TONE: Dramatic storytelling. Like a mini-documentary. Make it feel cinematic.
LENGTH: 6-10 minutes (18-25 scenes)
""",
    "brand_history": """You are a YouTube script writer for a car education channel using stickman animations.
FORMAT: Brand History — origin story of one car brand.
Structure:
1. Hook: most surprising fact about the brand
2. Founder's story
3. First car / early struggles
4. Breakthrough moment
5. Rise to fame / key models
6. Controversies or near-collapses (if any)
7. Where they are today
8. What makes them unique

TONE: Like a mini-documentary. Dramatic. Include specific dates, names, numbers.
LENGTH: 7-10 minutes (20-28 scenes)
""",
    "part_history": """You are a YouTube script writer for a car education channel using stickman animations.
FORMAT: Part History — invention and evolution of one car part.
Structure:
1. Hook: life before this part existed (or a dramatic failure)
2. Who invented it and why
3. Early versions and problems
4. How it evolved decade by decade
5. Modern version and how it works today
6. Fun facts

TONE: Mix of history and engineering. Make the invention story feel like a thriller.
LENGTH: 5-8 minutes (15-20 scenes)
"""
}

USED_TOPICS_FILE = "used_topics.json"

def load_used_topics():
    if Path(USED_TOPICS_FILE).exists():
        with open(USED_TOPICS_FILE) as f:
            return json.load(f)
    return {k: [] for k in FORMULAS}

def save_used_topics(used):
    with open(USED_TOPICS_FILE, "w") as f:
        json.dump(used, f, indent=2)

def pick_formula_and_topic():
    """Pick today's formula and topic, rotating through all formulas."""
    used = load_used_topics()
    
    # Rotate formula based on day of year
    formula_keys = list(FORMULAS.keys())
    day_of_year = datetime.now().timetuple().tm_yday
    formula_key = formula_keys[day_of_year % len(formula_keys)]
    
    formula = FORMULAS[formula_key]
    used_for_formula = used.get(formula_key, [])
    
    # Get unused topics
    available = [t for t in formula["topics"] if t not in used_for_formula]
    
    # If all used, reset
    if not available:
        used[formula_key] = []
        available = formula["topics"]
    
    topic = random.choice(available)
    used[formula_key].append(topic)
    save_used_topics(used)
    
    return formula_key, topic

def _sanitize_json_control_chars(raw: str) -> str:
    """
    LLMs sometimes emit literal control characters (raw newlines, tabs, etc.)
    inside JSON string values instead of escaping them (\\n, \\t). Strict JSON
    parsers reject this. This walks the raw text char-by-char, tracking
    whether we're inside a string literal, and escapes any raw control
    character (ASCII < 0x20) found inside a string so json.loads succeeds.
    """
    out = []
    in_string = False
    escaped = False
    for ch in raw:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ord(ch) < 0x20:
                # Escape raw control characters found inside a string
                if ch == "\n":
                    out.append("\\n")
                elif ch == "\t":
                    out.append("\\t")
                elif ch == "\r":
                    out.append("\\r")
                else:
                    out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def generate_script(formula_key=None, topic=None):
    """Generate a full script. If no formula/topic given, picks automatically."""
    if formula_key is None or topic is None:
        formula_key, topic = pick_formula_and_topic()
    
    formula = FORMULAS[formula_key]
    system_prompt = SYSTEM_PROMPTS[formula_key]
    min_scenes = formula["min_scenes"]
    min_words = formula["min_words"]
    
    full_system = system_prompt + f"""
HARD REQUIREMENT — DO NOT GO UNDER THIS: the "narration" field must contain
AT LEAST {min_words} words, and the "scenes" array must contain AT LEAST
{min_scenes} scene objects. This is a strict minimum, not a target — videos
that come in short will be rejected. If you are unsure, write more, not less.

You MUST respond with ONLY valid JSON, no markdown, no preamble:
{{
  "formula": "formula_key_here",
  "topic": "topic here",
  "title": "YouTube video title",
  "description": "YouTube description — 3 paragraphs, keyword-rich, ends with 15-20 hashtags. Include keywords like: cars explained, car education, how cars work, automotive explained, car facts",
  "tags": ["tag1", "tag2", ... 20 tags mixing broad + specific car terms],
  "thumbnail_text": "Bold 3-5 word text for thumbnail overlay (e.g. 'EVERY ENGINE EXPLAINED')",
  "thumbnail_visual": "Description of what stickman illustration to show on thumbnail — dramatic, eye-catching",
  "narration": "The FULL narration as one continuous string. Natural speech, conversational, uses pauses with commas and ellipses.",
  "scenes": [
    {{
      "id": 1,
      "narration_excerpt": "Exact sentence(s) from narration for this scene",
      "image_prompt": "Stickman illustration: white background, black outlines, simple labeled diagram. Describe exactly what to show.",
      "scene_description": "Brief note on what this scene covers"
    }}
  ]
}}

Rules:
- narration_excerpt must be exact substrings of the full narration
- image_prompt: always white background, stickman art style
- Tags must include: cars, car education, automotive, car facts, car explained + specific topic tags
- Title must use a proven viral formula (curiosity gap, numbers, superlatives)
- Remember: narration must be AT LEAST {min_words} words and scenes must number AT LEAST {min_scenes}
"""

    max_attempts = 3
    last_error = None
    for attempt in range(1, max_attempts + 1):
        user_msg = f"Write a {formula['name']} script about: {topic}"
        if attempt > 1:
            user_msg += (
                f"\n\nYour previous attempt was too short. You MUST write at least "
                f"{min_words} words of narration and at least {min_scenes} scenes. "
                f"Expand the explanation with more detail, examples, and sub-points."
            )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.7,
            max_tokens=8000,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = _sanitize_json_control_chars(raw)

        try:
            script = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = e
            print(f"  Attempt {attempt}: JSON parse failed ({e}), retrying...")
            continue

        word_count = len(script.get("narration", "").split())
        scene_count = len(script.get("scenes", []))

        if word_count >= min_words and scene_count >= min_scenes:
            script["formula"] = formula_key
            script["topic"] = topic
            return script

        last_error = (
            f"Too short: {word_count} words (need {min_words}), "
            f"{scene_count} scenes (need {min_scenes})"
        )
        print(f"  Attempt {attempt}: {last_error}, retrying...")

    # All attempts exhausted — return the last script anyway rather than
    # crashing the pipeline, but flag it loudly so it's not silently short.
    print(f"  WARNING: could not meet minimum length after {max_attempts} attempts "
          f"({last_error}). Proceeding with shortest available script.")
    script["formula"] = formula_key
    script["topic"] = topic
    return script


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        fkey, top = sys.argv[1], sys.argv[2]
        script = generate_script(fkey, top)
    else:
        script = generate_script()
    print(f"Formula: {script['formula']} | Topic: {script['topic']}")
    print(f"Title: {script['title']}")
    print(f"Scenes: {len(script['scenes'])}")
    with open("test_script.json", "w") as f:
        json.dump(script, f, indent=2)
    print("Saved to test_script.json")
