"""
Metadata generator — creates metadata.txt for Amazon KDP upload.
Includes title, series, description, keywords, ISBN placeholder, prices, age range.
"""
import json
import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def generate_metadata(story_json_path, output_path, title=None):
    """Generate KDP metadata from the story."""

    with open(story_json_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    # Try to generate a title from Ollama
    if title is None:
        title = _generate_title(story)

    # Generate description
    description = _generate_description(story, title)

    # Generate keywords
    keywords = _generate_keywords(story, title)

    metadata = f"""================================================================
AMAZON KDP METADATA
================================================================

TITLE: {title}

SERIES: {config.SERIES_NAME}
SERIES NUMBER: 1

DESCRIPTION:
{description}

KEYWORDS (max 7):
1. {keywords[0] if len(keywords) > 0 else 'children dinosaur book'}
2. {keywords[1] if len(keywords) > 1 else 'funny kids book'}
3. {keywords[2] if len(keywords) > 2 else 'dinosaur bedtime story'}
4. {keywords[3] if len(keywords) > 3 else 'read aloud book'}
5. {keywords[4] if len(keywords) > 4 else 'preschool dinosaur'}
6. {keywords[5] if len(keywords) > 5 else 'T-Rex kids book'}
7. {keywords[6] if len(keywords) > 6 else 'dino tails series'}

ISBN: [PLACEHOLDER — Purchase from Bowker or use KDP free ISBN]

PRICE (USD):
  Paperback: $9.99
  Hardcover: $19.99
  Kindle eBook: $2.99

AGE RANGE: 3-7 years
GRADE RANGE: Preschool - 2nd Grade

PAGE COUNT: {len(story)}
TRIM SIZE: 8.5 x 8.5 inches
INTERIOR: Premium Color
PAPER: White

CATEGORIES:
  - Children's Books > Animals > Dinosaurs
  - Children's Books > Humor

LANGUAGE: English
PUBLICATION DATE: [SET ON KDP]

================================================================
"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(metadata)

    print(f"[Metadata] Saved to {output_path}")
    return title


def _generate_title(story):
    """Try to generate a title using Ollama."""
    try:
        first_pages = " ".join(p["text"] for p in story[:5])
        prompt = f"""Based on this children's story from the "Dino Tails" series about Rexi the baby T-Rex, suggest ONE short catchy book title (max 8 words). Return ONLY the title, nothing else.

Story excerpt: {first_pages}"""

        url = f"{config.OLLAMA_URL}/api/generate"
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 50}
        }

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        title = response.json().get("response", "").strip().strip('"\'')

        if title and len(title) < 100:
            print(f"[Metadata] Generated title: {title}")
            return title
    except Exception as e:
        print(f"[Metadata] Could not generate title: {e}")

    return "Rexi's Big Day"


def _generate_description(story, title):
    """Generate a book description."""
    try:
        full_text = " ".join(p["text"] for p in story[:6])
        prompt = f"""Write a short Amazon book description (3-4 sentences) for a children's book titled "{title}" from the "Dino Tails" series about Rexi, a cute baby T-Rex with tiny arms who creatively solves problems with help from his dinosaur friends. Make it appealing to parents. Return ONLY the description.

Story excerpt: {full_text}"""

        url = f"{config.OLLAMA_URL}/api/generate"
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 200}
        }

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        desc = response.json().get("response", "").strip()

        if desc and len(desc) > 20:
            return desc
    except Exception as e:
        print(f"[Metadata] Could not generate description: {e}")

    return (
        f"Meet Rexi — a tiny T-Rex with even tinier arms but the BIGGEST imagination! "
        f"In \"{title}\", part of the Dino Tails series, Rexi tackles impossible challenges "
        f"with creative solutions and help from his prehistoric pals. A laugh-out-loud dinosaur "
        f"adventure that teaches kids about creativity, friendship, and never giving up. Perfect for ages 3-7."
    )


def _generate_keywords(story, title):
    """Generate KDP keywords."""
    default_keywords = [
        "children dinosaur book",
        "funny kids book",
        "dinosaur bedtime story",
        "read aloud book",
        "preschool dinosaur",
        "T-Rex kids book",
        "dino tails series"
    ]

    try:
        prompt = f"""List exactly 7 Amazon KDP search keywords for a funny children's picture book titled "{title}" from the "Dino Tails" series about Rexi, a cute baby T-Rex with tiny arms who has adventures with his dinosaur friends. Return ONLY a JSON array of 7 strings, nothing else.

Example: ["keyword one", "keyword two", ...]"""

        url = f"{config.OLLAMA_URL}/api/generate"
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 200}
        }

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        raw = response.json().get("response", "").strip()

        # Parse JSON array
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            keywords = json.loads(raw[start:end + 1])
            if isinstance(keywords, list) and len(keywords) >= 7:
                return keywords[:7]
    except Exception as e:
        print(f"[Metadata] Could not generate keywords: {e}")

    return default_keywords


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        generate_metadata(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python metadata.py <story.json> <metadata.txt>")
        sys.exit(1)
