"""
Generate a 24-page funny children's story for the "Dino Tails" series using Ollama.
Reads book_context.md as world bible and series_list.txt for repetition avoidance.
Rotates POV characters. Saves structured JSON with page number and text.
Retries 3 times on failure.
"""
import json
import logging
import re
import sys
import os
import time
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_path = Path(config.LOGS_DIR) / "pipeline.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Story Gen] %(message)s",
    handlers=[
        logging.FileHandler(str(_log_path), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# World bible loader
# ---------------------------------------------------------------------------
def _load_book_context() -> str:
    """Read book_context.md and return full text, or empty string."""
    ctx_path = Path(config.BOOK_CONTEXT_PATH)
    if ctx_path.exists():
        return ctx_path.read_text(encoding="utf-8")
    logger.warning("book_context.md not found at %s", ctx_path)
    return ""


# ---------------------------------------------------------------------------
# Series list helpers
# ---------------------------------------------------------------------------
def _load_existing_titles() -> list[str]:
    """Read series_list.txt and return list of existing book titles."""
    sl_path = Path(config.SERIES_LIST_PATH)
    if not sl_path.exists():
        return []
    titles: list[str] = []
    for line in sl_path.read_text(encoding="utf-8").splitlines():
        # Lines like: "#001 — Rexi's Tail-Painting Tangle"
        m = re.match(r"^#\d+\s*[—-]\s*(.+)$", line.strip())
        if m:
            titles.append(m.group(1).strip())
    return titles


def _load_recent_pov_characters(n: int = 3) -> list[str]:
    """Return the last *n* POV character names from series_list.txt."""
    sl_path = Path(config.SERIES_LIST_PATH)
    if not sl_path.exists():
        return []
    povs: list[str] = []
    for line in sl_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^POV Character:\s*(.+)$", line.strip())
        if m:
            povs.append(m.group(1).strip())
    return povs[-n:] if povs else []


def choose_pov_character() -> str:
    """Choose next POV character using rotation rules.

    If Rexi has been POV for the last 3 books in a row, pick a different
    character. Rotates through all 5 characters.
    """
    recent = _load_recent_pov_characters(3)
    all_chars = config.POV_CHARACTERS

    # If Rexi appeared 3 times in a row, exclude Rexi this round
    if len(recent) >= 3 and all(c == "Rexi" for c in recent):
        candidates = [c for c in all_chars if c != "Rexi"]
    else:
        candidates = list(all_chars)

    # Find the least-recently-used character among candidates
    for candidate in candidates:
        if candidate not in recent:
            return candidate

    # All candidates appeared recently — pick last in rotation order
    return candidates[0]


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------
def generate_story(output_path: str, num_pages: int | None = None,
                   pov_character: str | None = None,
                   critique: str | None = None,
                   max_retries: int = 3) -> list | None:
    """Generate a children's story using Ollama and save as JSON.

    If *critique* is provided (from a previous review), the model is instructed
    to fix every listed problem before writing the new version.
    """
    if num_pages is None:
        num_pages = config.NUM_PAGES

    if pov_character is None:
        pov_character = choose_pov_character()

    logger.info("POV character for this book: %s", pov_character)

    # Load world bible
    world_bible = _load_book_context()

    # Load existing titles for repetition avoidance
    existing_titles = _load_existing_titles()
    existing_titles_block = ""
    if existing_titles:
        titles_str = "\n".join(f"  - {t}" for t in existing_titles)
        existing_titles_block = (
            f"\n\nExisting books in the series (DO NOT reuse any of these ideas, "
            f"locations used in the last 5, or problems from the last 3):\n{titles_str}\n"
        )

    # Build critique block (injected when rewriting after a failed review)
    critique_block = ""
    if critique:
        critique_block = (
            f"\n\n=== MANDATORY FIXES FROM PREVIOUS REVIEW ===\n"
            f"{critique}\n"
            f"You MUST fix every single one of these problems in the new version. "
            f"Do not reproduce any of the flaws listed above.\n"
            f"=== END OF MANDATORY FIXES ===\n"
        )
        logger.info("Rewriting with critique: %s", critique[:200])

    # Build the prompt
    prompt = f"""You are a children's book author writing for the "Dino Tails" series.

=== WORLD BIBLE (absolute canon — follow exactly) ===
{world_bible}
=== END WORLD BIBLE ===
{existing_titles_block}
Write a funny {num_pages}-page children's story.

The POV character for this book is {pov_character}. The story is written from {pov_character}'s point of view — {pov_character} drives the plot, faces the main challenge, and appears on every page. Other characters from the world bible may appear as supporting characters.

{critique_block}
=== STRUCTURE REQUIREMENTS (follow this arc exactly) ===
Pages 1-3: Normal day. Establish {pov_character}'s goal or desire clearly.
Pages 4-6: {pov_character} makes a bold decision. Lonnie says "I have a bad feeling about this" EXACTLY ONCE and only here.
Pages 7-12: Three escalating failures. Each one is WORSE and FUNNIER than the last. Make each failure a DIFFERENT type (physical, social, accidental). Avoid repeating the same joke.
Pages 13-18: The most disastrous moment. Everything goes spectacularly wrong at once. This should be the funniest part of the book — surprising and unexpected.
Pages 19-21: Everyone works together to fix the chaos. The solution must USE {pov_character}'s specific weakness or running gag in a clever way.
Pages 22-23: Resolution. The original goal is achieved but not in the way anyone expected. Something funny is different now.
Page 24: Short, punchy final line. Everyone is happy, slightly muddy, and ready for the next adventure.
=== END STRUCTURE ===

=== HUMOR RULES ===
- Pick ONE main humor style for this book: unexpected role reversal, escalating misunderstanding, or absurd solution
- Do NOT repeat the same joke type more than twice in the whole book
- At least two jokes must involve {pov_character}'s specific running gag from the world bible
- One joke must surprise the reader by reversing an expectation set up 3+ pages earlier
- The funniest line should be on page 13-18, not at the end
=== END HUMOR RULES ===

Rules:
- Exactly {num_pages} pages
- Each page: MAXIMUM 2 sentences. Keep each sentence under 12 words.
- KEEP IT SHORT. Each page text should be 15-25 words total.
- Vocabulary: no words above second-grade level
- Each page must describe a scene that can be illustrated with one clear image
- Never reuse a story idea from the existing series list above
- All characters, locations, and world rules must match the world bible above

Return ONLY valid JSON in this exact format, with no other text before or after:
[
  {{"page": 1, "text": "Page 1 text here"}},
  {{"page": 2, "text": "Page 2 text here"}},
  ...
  {{"page": {num_pages}, "text": "Page {num_pages} text here"}}
]"""

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Attempt %d/%d...", attempt, max_retries)
            url = f"{config.OLLAMA_URL}/api/generate"
            payload = {
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "think": False,   # suppress <think> preamble on gemma3/qwen3
                "options": {
                    "temperature": 0.8,
                    "num_predict": 12000,  # 4096 truncated 24-page stories mid-JSON
                },
            }

            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()

            result = response.json()
            raw_text = result.get("response", "")

            story = _parse_story_json(raw_text, num_pages)

            if story and len(story) >= max(20, num_pages - 4):
                # Pad missing pages if slightly short
                while len(story) < num_pages:
                    last = story[-1]
                    story.append({"page": last["page"] + 1, "text": story[min(len(story)-1, 23-1)]["text"]})
                story = story[:num_pages]  # trim if over
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                # Enforce text limits for better readability
                story = _enforce_text_limits(story)

                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(story, f, indent=2, ensure_ascii=False)

                logger.info("Success! %d pages saved to %s", len(story), output_path)

                # Check for new characters/locations not in world bible
                _check_canon_compliance(story, world_bible)

                return story

            logger.warning(
                "Got %d pages, expected %d. Retrying...",
                len(story) if story else 0,
                num_pages,
            )

        except requests.exceptions.RequestException as e:
            logger.warning("Network error on attempt %d: %s", attempt, e)
        except Exception as e:
            logger.warning("Error on attempt %d: %s", attempt, e)

        if attempt < max_retries:
            time.sleep(5)

    logger.error("FAILED after all retries.")
    return None


# ---------------------------------------------------------------------------
# Canon compliance checker
# ---------------------------------------------------------------------------
_KNOWN_NAMES = {"rexi", "lonnie", "pterry", "spike", "mara"}

def _check_canon_compliance(story: list, world_bible: str) -> None:
    """Log a suggestion if a new proper noun appears 3+ times, suggesting a new character."""
    import re as _re
    import collections
    full_text = " ".join(p["text"] for p in story)
    all_words = _re.findall(r"\b[A-Z][a-z]{3,}\b", full_text)
    counts = collections.Counter(all_words)
    bible_lower = world_bible.lower()
    for w, count in counts.items():
        if count >= 3 and w.lower() not in _KNOWN_NAMES and w.lower() not in bible_lower:
            logger.info(
                "SUGGESTION: '%s' appears %d times and may be a new character or location — "
                "consider adding to book_context.md manually.",
                w, count,
            )


def _enforce_text_limits(story: list) -> list:
    """Enforce text limits for each page to ensure readability."""
    for page in story:
        text = page["text"]
        # If text is too long, truncate it
        if len(text) > 150:
            # Split into sentences and keep only enough to stay under limit
            sentences = text.split('. ')
            new_text = ""
            for sentence in sentences:
                if len(new_text) + len(sentence) + 2 <= 140:  # Leave some buffer
                    new_text += sentence + ". "
                else:
                    break
            page["text"] = new_text.strip() or text[:140] + "..."
    return story


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------
def _parse_story_json(raw_text: str, expected_pages: int) -> list | None:
    """Extract and parse JSON story from Ollama response."""
    import re as _re

    def _sanitize(s: str) -> str:
        """Strip wrappers and normalize quotes so JSON parses cleanly."""
        # Strip <think>...</think> blocks
        s = _re.sub(r"<think>.*?</think>", "", s, flags=_re.DOTALL).strip()
        # Strip markdown code fences
        s = s.replace("```json", "").replace("```", "").strip()
        # Normalize smart/curly quotes → straight (apostrophes in contractions break JSON)
        s = s.replace("\u2018", "'").replace("\u2019", "'")
        s = s.replace("\u201c", '"').replace("\u201d", '"')
        return s

    raw_text = _sanitize(raw_text)

    try:
        data = json.loads(raw_text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw_text[start:end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        out = sys.argv[1]
    else:
        paths = config.get_book_paths("test_story")
        out = paths["story_json"]

    result = generate_story(out)
    if result:
        print(f"Generated {len(result)} pages")
    else:
        print("Story generation failed")
        sys.exit(1)
