"""
AI Review — sends story to Ollama for quality scoring.
Scores: grammar, humor, readability, consistency (each out of 10).
Writes PASS or FAIL to review_status.txt. Average below 7 is FAIL.
"""
import json
import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def review_story(story_json_path, review_status_path, review_details_path, max_retries=3):
    """Send story to Ollama for AI review and write PASS/FAIL."""

    # Load story
    with open(story_json_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    # Build full story text
    full_text = "\n\n".join(
        f"Page {page['page']}: {page['text']}" for page in story
    )

    prompt = f"""You are a children's book editor scoring a story for ages 3-7 for Amazon KDP publication.

Score this story on FOUR criteria, each out of 10. Use the full range: 7 means solid and publishable, 8 means genuinely good, 9 means excellent, 10 is near-perfect.

GRAMMAR (1-10): Score 7 if sentences are clear and age-appropriate with only minor issues. Deduct for run-ons, awkward phrasing, inconsistent tense.

HUMOR (1-10): Score 7 if the story has at least 2 genuinely funny moments a child would enjoy. Deduct if jokes are flat or repetitive. Give 8+ if a parent would also smile.

READABILITY (1-10): Score 7 if sentences are short (under 15 words), vocabulary is simple, and story flows naturally page to page. Deduct for long sentences or complex words.

CONSISTENCY (1-10): Score 7 if the story has a clear beginning/middle/end, characters act consistently, and the resolution makes sense. Deduct for logic gaps or rushed endings.

Be fair but specific. Note at least 1 genuine flaw.

Here is the story to review:

{full_text}

Return ONLY valid JSON in this exact format, no other text:
{{
  "grammar": <integer 1-10>,
  "humor": <integer 1-10>,
  "readability": <integer 1-10>,
  "consistency": <integer 1-10>,
  "comments": "Specific flaws found"
}}"""

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[AI Review] Attempt {attempt}/{max_retries}...")
            url = f"{config.OLLAMA_URL}/api/generate"
            payload = {
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1024
                }
            }

            response = requests.post(url, json=payload, timeout=180)
            response.raise_for_status()

            result = response.json()
            raw_text = result.get("response", "")

            scores = _parse_review_json(raw_text)

            if scores:
                avg = (
                    scores["grammar"] +
                    scores["humor"] +
                    scores["readability"] +
                    scores["consistency"]
                ) / 4.0

                scores["average"] = round(avg, 2)
                status = "PASS" if avg >= 7.0 else "FAIL"
                scores["status"] = status

                # Write review details
                os.makedirs(os.path.dirname(review_details_path), exist_ok=True)
                with open(review_details_path, "w", encoding="utf-8") as f:
                    json.dump(scores, f, indent=2)

                # Write status file
                with open(review_status_path, "w", encoding="utf-8") as f:
                    f.write(status)

                print(f"[AI Review] Scores — Grammar: {scores['grammar']}, "
                      f"Humor: {scores['humor']}, Readability: {scores['readability']}, "
                      f"Consistency: {scores['consistency']}")
                print(f"[AI Review] Average: {avg:.2f} — {status}")
                return scores

            print(f"[AI Review] Could not parse scores. Retrying...")

        except requests.exceptions.RequestException as e:
            print(f"[AI Review] Network error on attempt {attempt}: {e}")
        except Exception as e:
            print(f"[AI Review] Error on attempt {attempt}: {e}")

        if attempt < max_retries:
            time.sleep(5)

    # If all retries fail, write FAIL
    with open(review_status_path, "w", encoding="utf-8") as f:
        f.write("FAIL")
    print("[AI Review] FAILED after all retries.")
    return None


def _parse_review_json(raw_text):
    """Extract review scores from Ollama response."""
    import re as _re
    # Strip <think>...</think> blocks (gemma3/qwen3 thinking models)
    raw_text = _re.sub(r"<think>.*?</think>", "", raw_text, flags=_re.DOTALL).strip()

    # Try direct parse
    try:
        data = json.loads(raw_text.strip())
        if _validate_scores(data):
            return data
    except json.JSONDecodeError:
        pass

    # Try to find JSON object
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw_text[start:end + 1])
            if _validate_scores(data):
                return data
        except json.JSONDecodeError:
            pass

    # Clean markdown
    try:
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        if _validate_scores(data):
            return data
    except json.JSONDecodeError:
        pass

    return None


def _validate_scores(data):
    """Check that all required score fields exist and are valid."""
    required = ["grammar", "humor", "readability", "consistency"]
    for key in required:
        if key not in data:
            return False
        try:
            val = float(data[key])
            if val < 1 or val > 10:
                return False
            data[key] = val
        except (ValueError, TypeError):
            return False
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        review_story(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("Usage: python ai_review.py <story.json> <review_status.txt> <review_details.json>")
        sys.exit(1)
