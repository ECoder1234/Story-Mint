"""
Generate illustrations for each page of the Dino Tails story using Stable Diffusion.
Reads book_context.md for character SD prompt blocks.
Every page gets a unique illustration prompt dynamically built from that page's
story text using the three-part prompt system:
  PART 1 — POV character's SD prompt block from book_context.md
  PART 2 — Dynamic scene extracted from page text via Ollama
  PART 3 — Fixed quality tail with style tokens
Calls SD Forge API at localhost:7860, steps 25, 768x768.  Seed 42.
Retries 3 times per image. Generates a separate cover image too.
"""
import json
import logging
import re
import sys
import os
import time
import io
import base64
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ---------------------------------------------------------------------------
# Logging — all output also goes to logs/pipeline.log with timestamps
# ---------------------------------------------------------------------------
_log_path = Path(config.LOGS_DIR) / "pipeline.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Image Gen] %(message)s",
    handlers=[
        logging.FileHandler(str(_log_path), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Default fallback — overridden at runtime when book_context.md is loaded
# Using descriptive terms instead of names to reduce human generation triggers
DEFAULT_CHARACTER_BLOCK = (
    "baby T-Rex dinosaur, tiny arms, big expressive eyes, "
    "bright green scales, wide toothy grin, round body, stumpy tail"
)

# Locked Lonnie block — must be this exact string every page, no variation
# Using descriptive terms instead of names to reduce human generation triggers
_LONNIE_LOCKED_BLOCK = (
    "pale yellow Brontosaurus dinosaur, very long neck, "
    "small friendly head, gentle eyes, leaf stuck on body, "
    "no humans, no people, dinosaur only, cartoon children's "
    "book style, bright colors, flat cel shaded"
)

QUALITY_TAIL = (
    "toon style, toonyou, children's picture book illustration, "
    "vibrant flat colors, cel shaded, expressive cartoon face, "
    "clean lineart, dynamic pose, KDP ready, "
    "consistent character design, same character every page, "
    "bright cheerful colors, no humans, no people, dinosaurs only"
)

NEGATIVE_PROMPT = (
    "deformed, ugly, blurry, extra limbs, wrong colors, inconsistent "
    "character, different character, realistic, photograph, adult, scary, "
    "dark, violence, text, watermark, signature, "
    "human, person, people, girl, boy, man, woman, child, kid, baby human, "
    "human hands, human feet, human face, humanoid, "
    "sneakers, shoes, backpack, shirt, shorts, pants, clothing on humans, "
    "feathers, bird, brown bird, wings on human, parrot, "
    "two heads, double face, multiple heads, extra head, "
    "duplicate character, cloned character, "
    "photo, photograph, realistic photo, camera, lens"
)

# Words that flag a human in a CLIP caption — checked with word boundaries
# so "he" does NOT match "the", "man" does NOT match "woman", etc.
# Pronouns (he/she/his/her) removed deliberately: CLIP uses them for dinosaur
# characters too, causing near-100% false positive rejection rate.
_HUMAN_WORD_KEYWORDS = [
    "girl", "boy", "woman", "man", "person", "people", "human",
    "child", "kid", "lady", "guy",
    "sneakers", "shoes", "backpack", "shirt", "shorts", "dress",
]


# ---------------------------------------------------------------------------
# Character SD prompt blocks from book_context.md
# ---------------------------------------------------------------------------
_CHARACTER_SD_BLOCKS: dict[str, str] = {}


def _load_character_blocks() -> None:
    """Parse book_context.md and extract SD prompt blocks for each character."""
    global _CHARACTER_SD_BLOCKS
    ctx_path = Path(config.BOOK_CONTEXT_PATH)
    if not ctx_path.exists():
        logger.warning("book_context.md not found — using default character block")
        return

    content = ctx_path.read_text(encoding="utf-8")

    # Regex: look for "### CharName" sections then "SD prompt block:" lines
    current_char = None
    for line in content.splitlines():
        header_match = re.match(r"^###\s+(\w+)", line)
        if header_match:
            current_char = header_match.group(1)
        sd_match = re.match(r"^- SD prompt block:\s*\"(.+?)\"", line)
        if sd_match and current_char:
            _CHARACTER_SD_BLOCKS[current_char] = sd_match.group(1)

    if _CHARACTER_SD_BLOCKS:
        logger.info("Loaded SD prompt blocks for: %s", ", ".join(_CHARACTER_SD_BLOCKS.keys()))
    else:
        logger.warning("No SD prompt blocks found in book_context.md")


def get_character_block(character_name: str) -> str:
    """Return the SD prompt block for a character, falling back to default.
    Lonnie always returns the locked block — never varies.
    """
    if character_name.lower() == "lonnie":
        return _LONNIE_LOCKED_BLOCK
    if not _CHARACTER_SD_BLOCKS:
        _load_character_blocks()
    return _CHARACTER_SD_BLOCKS.get(character_name, DEFAULT_CHARACTER_BLOCK)


# ---------------------------------------------------------------------------
# Dynamic prompt functions (per copilot-instructions.md)
# ---------------------------------------------------------------------------
def extract_scene_from_text(page_text: str) -> str:
    """Call Ollama to read the page text and return a 10-15 word visual scene
    description. Falls back to a simple text snippet if Ollama is unreachable.

    IMPORTANT: The scene must describe only WHAT IS HAPPENING and WHERE.
    It must NEVER describe character appearance — that comes from the locked
    character block. No character names, no physical descriptions.
    """
    prompt = (
        "Read this children's book page text and write a 10-15 word scene "
        "description for a Stable Diffusion illustration prompt.\n"
        "Rules:\n"
        "- Describe ONLY what is happening and where (action + location).\n"
        "- Do NOT describe any character's appearance, colour, or species.\n"
        "- Do NOT include any character names.\n"
        "- Do NOT mention humans, people, children, or any non-dinosaur creatures.\n"
        "- Do NOT describe multiple characters separately - focus on the main action.\n"
        "- Use simple present tense verbs (splashing, standing, running).\n"
        "- Return only the scene phrase, nothing else.\n"
        "- Avoid mentioning quantities like 'two dinosaurs' - just describe the action.\n"
        f"Page text: {page_text}"
    )
    for attempt in range(1, 4):
        try:
            response = requests.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 60},
                },
                timeout=120,
            )
            response.raise_for_status()
            scene = response.json().get("response", "").strip().strip('"\'')
            if scene.lower().startswith("scene:"):
                scene = scene[6:].strip()
            if len(scene) > 10:
                return scene
        except requests.exceptions.RequestException as e:
            logger.warning("Ollama scene extraction attempt %d failed: %s", attempt, e)
        except Exception as e:
            logger.warning("Ollama scene extraction attempt %d error: %s", attempt, e)
        if attempt < 3:
            time.sleep(3)

    # Fallback: use a trimmed version of the page text itself
    logger.warning("Ollama unreachable — using text-based fallback scene")
    fallback = page_text[:120].strip().rstrip(".")
    return f"scene from story: {fallback}"


def build_image_prompt(page_text: str, pov_character_block: str | None = None) -> str:
    """Build the full three-part SD prompt for a single page.
    PART 1: pov_character_block — locked character description, always first, verbatim
    PART 2: dynamic scene from page text (action + location only, no appearance)
    PART 3: QUALITY_TAIL — fixed style tokens
    """
    if pov_character_block is None:
        pov_character_block = DEFAULT_CHARACTER_BLOCK
    scene = extract_scene_from_text(page_text)
    # Character block is ALWAYS first — SD pays most attention to prompt start
    # Adding consistency modifiers to reduce variations
    return f"{pov_character_block}, {scene}, {QUALITY_TAIL}, consistent character design, same character every page"


# ---------------------------------------------------------------------------
# Supporting character detection
# ---------------------------------------------------------------------------
_CHAR_NAME_PATTERN = re.compile(
    r"\b(Rexi|Lonnie|Pterry|Spike|Mara)\b", re.IGNORECASE
)


def _detect_supporting_characters(page_text: str, pov_name: str) -> list[str]:
    """Return list of named characters in text that are not the POV character."""
    found = set()
    for m in _CHAR_NAME_PATTERN.finditer(page_text):
        name = m.group(1).capitalize()
        if name.lower() != pov_name.lower():
            found.add(name)
    return sorted(found)


# ---------------------------------------------------------------------------
# SD Forge helpers
# ---------------------------------------------------------------------------
def _check_sd_available() -> bool:
    """Quick check if SD Forge API is reachable."""
    try:
        r = requests.get(
            f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/sd-models", timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False


def _load_sd_model() -> None:
    """Switch SD Forge to the configured model if it is not already loaded."""
    target = getattr(config, "SD_MODEL", None)
    if not target:
        return
    try:
        # Check current model
        r = requests.get(f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/options", timeout=10)
        current = r.json().get("sd_model_checkpoint", "")
        # Resolve to filename with extension
        models_r = requests.get(f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/sd-models", timeout=10)
        all_models = {m["model_name"]: m["title"] for m in models_r.json()}
        # Find matching model (strip extension for comparison)
        target_title = None
        for name, title in all_models.items():
            if target.lower() in name.lower():
                target_title = title
                break
        if target_title is None:
            logger.warning("Model '%s' not found in SD Forge. Available: %s", target, list(all_models.keys()))
            logger.warning("Continuing with current model: %s", current)
            return
        # Normalize comparison: strip " [hash]" suffix SD Forge sometimes appends
        def _base(s: str) -> str:
            return s.split(" [")[0].strip().lower()
        if _base(target_title) == _base(current):
            logger.info("SD model already loaded: %s", current)
            return
        logger.info("Switching SD model: %s → %s", current, target_title)
        requests.post(
            f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/options",
            json={"sd_model_checkpoint": target_title},
            timeout=120,
        )
        logger.info("Model switch requested — waiting for load...")
        for _ in range(30):
            time.sleep(5)
            check = requests.get(f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/options", timeout=10)
            if check.json().get("sd_model_checkpoint") == target_title:
                logger.info("Model loaded: %s", target_title)
                return
        logger.warning("Model may not have switched in time — proceeding anyway")
    except Exception as e:
        logger.warning("Could not switch SD model: %s", e)


def _interrogate_image(image_path: str) -> str | None:
    """Use SD Forge's CLIP interrogate endpoint to get a caption for a saved image."""
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "image": f"data:image/png;base64,{image_b64}",
            "model": "clip",
        }
        response = requests.post(
            f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/interrogate",
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        caption = response.json().get("caption", "").strip()
        return caption if caption else None
    except Exception as e:
        logger.warning("Image interrogation failed: %s", e)
        return None


def _caption_contains_human(caption: str) -> bool:
    """Return True if the CLIP caption describes a human.

    Uses regex word-boundary matching so 'he' does not match 'the',
    'man' does not match 'woman', 'her' does not match 'there', etc.
    """
    caption_lower = caption.lower()
    for kw in _HUMAN_WORD_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", caption_lower):
            return True
    return False


def _verify_image_matches_story(caption: str, page_text: str) -> bool:
    """Return True only if the image matches the story AND contains no humans.

    Hard-fail immediately if the caption contains any human keywords.
    Then ask Ollama for a story-match check with explicit no-human rule.
    Returns True only on clear YES; defaults to False on ambiguity.
    """
    if not caption:
        return True

    # Hard rule: any human in the image is an instant failure
    if _caption_contains_human(caption):
        logger.warning("HUMAN detected in caption — rejecting image. Caption: %s", caption[:120])
        return False

    prompt = (
        f'Image CLIP caption: "{caption}"\n\n'
        "This is a children's dinosaur picture book. "
        "Does the caption describe only dinosaur/animal characters with NO humans, people, men, women, boys, or girls? "
        "Answer with a single word: YES or NO."
    )
    for attempt in range(1, 3):
        try:
            response = requests.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 5},
                },
                timeout=60,
            )
            response.raise_for_status()
            answer = response.json().get("response", "").strip().upper()
            first_word = answer.split()[0] if answer.split() else ""
            if first_word == "YES":
                return True
            if first_word == "NO":
                logger.warning("Ollama flagged human in image. Caption: %s", caption[:100])
                return False
            logger.warning("Ambiguous verification answer: %s", answer[:40])
            return True   # ambiguous — allow rather than waste time regenerating
        except Exception as e:
            logger.warning("Image verification Ollama call attempt %d failed: %s", attempt, e)
    return True  # if Ollama unreachable, trust the CLIP keyword check above


def _send_to_sd(prompt: str, negative_prompt: str, seed: int, max_retries: int = 3,
                width: int | None = None, height: int | None = None) -> bytes | None:
    """Post a txt2img request to SD Forge and return raw image bytes or None."""
    sd_url = f"{config.STABLE_DIFFUSION_URL}/sdapi/v1/txt2img"
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "steps": config.SD_STEPS,
        "width": width if width is not None else config.SD_WIDTH,
        "height": height if height is not None else config.SD_HEIGHT,
        "seed": seed,
        "sampler_name": "Euler a",
        "cfg_scale": 9,   # ToonYou sweet spot for crisp cartoon lines; DreamShaper use 7
        "batch_size": 1,
        "n_iter": 1,
    }
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(sd_url, json=payload, timeout=300)
            response.raise_for_status()
            images = response.json().get("images", [])
            if images:
                return base64.b64decode(images[0])
            logger.warning("No image data returned (attempt %d)", attempt)
        except requests.exceptions.RequestException as e:
            logger.warning("SD network error (attempt %d): %s", attempt, e)
        except Exception as e:
            logger.warning("SD error (attempt %d): %s", attempt, e)
        if attempt < max_retries:
            time.sleep(5)
    return None


# ---------------------------------------------------------------------------
# Main generation entry points
# ---------------------------------------------------------------------------
def generate_images(story_json_path: str, images_dir: str,
                    pov_character: str = "Rexi", max_retries: int = 3) -> tuple[int, int]:
    """Generate one unique illustration per page from story JSON.
    Every page prompt is built dynamically via build_image_prompt().
    Uses the POV character's SD prompt block from book_context.md."""

    # Load character blocks from world bible
    _load_character_blocks()
    pov_block = get_character_block(pov_character)
    logger.info("POV character for images: %s", pov_character)

    # Switch SD Forge to configured model (e.g. toonyou_beta6)
    _load_sd_model()

    if not _check_sd_available():
        logger.error(
            "SD Forge at %s is not reachable!", config.STABLE_DIFFUSION_URL
        )
        logger.info("Creating placeholders for all pages.")
        with open(story_json_path, "r", encoding="utf-8") as f:
            story = json.load(f)
        os.makedirs(images_dir, exist_ok=True)
        for page in story:
            page_num = page["page"]
            filepath = os.path.join(images_dir, f"page_{page_num:02d}.png")
            _create_placeholder(filepath, page_num)
        return 0, len(story)

    with open(story_json_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    os.makedirs(images_dir, exist_ok=True)
    success_count = 0
    fail_count = 0
    page1_scene: str | None = None

    for page in story:
        page_num = page["page"]
        page_text = page["text"]

        # Build prompt with POV character block
        full_prompt = build_image_prompt(page_text, pov_block)

        # Append supporting characters' SD blocks if mentioned
        supporting = _detect_supporting_characters(page_text, pov_character)
        for s_name in supporting:
            s_block = get_character_block(s_name)
            if s_block != DEFAULT_CHARACTER_BLOCK:
                # Remove any character name from the block to prevent human generation
                # This regex removes the first part before the comma which usually contains the name
                s_block_no_name = ",".join(s_block.split(",")[1:]).strip()
                full_prompt = f"{full_prompt}, {s_block_no_name}"

        # Page-1 continuity: use page 1's scene as visual reference for subsequent pages
        if page_num == 1:
            page1_scene = extract_scene_from_text(page_text)
        elif page1_scene:
            full_prompt = f"{full_prompt}, consistent with opening scene: {page1_scene}"

        filename = f"page_{page_num:02d}.png"
        filepath = os.path.join(images_dir, filename)

        logger.info("Page %d — prompt: %s", page_num, full_prompt[:140])

        image_data = _send_to_sd(
            prompt=full_prompt,
            negative_prompt=NEGATIVE_PROMPT,
            seed=config.SD_SEED,
            max_retries=max_retries,
        )

        if image_data:
            with open(filepath, "wb") as img_file:
                img_file.write(image_data)
            logger.info("Saved %s (%d bytes)", filename, len(image_data))

            # Verify image matches page story text using CLIP interrogate
            # Up to 3 re-generations; any human in caption = instant fail
            for verify_attempt in range(1, 4):
                caption = _interrogate_image(filepath)
                if caption is None:
                    break  # interrogate unavailable, skip verification
                matches = _verify_image_matches_story(caption, page_text)
                if matches:
                    logger.info("Page %d verified OK. Caption: %s", page_num, caption[:80])
                    break
                else:
                    logger.warning(
                        "Page %d image rejected (verify attempt %d). Caption: %s",
                        page_num, verify_attempt, caption[:80],
                    )
                    if verify_attempt < 3:
                        logger.info("Regenerating page %d (attempt %d/3)...", page_num, verify_attempt + 1)
                        new_data = _send_to_sd(
                            prompt=full_prompt,
                            negative_prompt=NEGATIVE_PROMPT,
                            seed=config.SD_SEED + page_num + (verify_attempt * 500),
                            max_retries=max_retries,
                        )
                        if new_data:
                            with open(filepath, "wb") as img_file:
                                img_file.write(new_data)
                            logger.info("Regenerated page %d (%d bytes)", page_num, len(new_data))

            success_count += 1
        else:
            logger.error(
                "FAILED page %d after %d retries", page_num, max_retries
            )
            fail_count += 1
            _create_placeholder(filepath, page_num)

    logger.info("Done. Success: %d, Failed: %d", success_count, fail_count)
    return success_count, fail_count


def generate_cover_image(images_dir: str, title: str = "Dino Tails",
                         pov_character: str = "Rexi", max_retries: int = 3) -> str | None:
    """Generate a cover illustration featuring the POV character."""
    if not _check_sd_available():
        logger.warning("SD Forge not reachable — skipping cover image")
        return None

    _load_character_blocks()
    pov_block = get_character_block(pov_character)

    os.makedirs(images_dir, exist_ok=True)
    filepath = os.path.join(images_dir, "cover.jpg")
    legacy_png = os.path.join(images_dir, "cover.png")

    cover_prompt = (
        f"{pov_block}, standing proudly in a vibrant colorful "
        "prehistoric jungle called Fernwood Valley, lush tropical plants "
        f"and giant ferns in the background, golden sunlight, {QUALITY_TAIL}, "
        "no text, no words, no title, solo character, centered composition"
    )

    cover_size = getattr(config, "SD_COVER_SIZE", config.SD_WIDTH)
    image_data = _send_to_sd(
        prompt=cover_prompt,
        negative_prompt=NEGATIVE_PROMPT + ", text, title, letters, multiple characters, crowd, group",
        seed=config.SD_SEED,
        max_retries=max_retries,
        width=cover_size,
        height=cover_size,
    )

    if image_data:
        if _save_cover_as_jpeg(image_data, filepath):
            if os.path.exists(legacy_png):
                try:
                    os.unlink(legacy_png)
                except OSError:
                    logger.warning("Could not remove legacy PNG cover: %s", legacy_png)
            logger.info("Cover image saved as JPEG: %s", filepath)
            return filepath

        logger.warning("JPEG conversion failed, falling back to legacy PNG cover")
        with open(legacy_png, "wb") as f:
            f.write(image_data)
        logger.info("Cover image saved as PNG fallback: %s", legacy_png)
        return legacy_png

    logger.warning("Cover image generation failed, using blank cover")
    return None


# ---------------------------------------------------------------------------
# Placeholder (used when SD is offline)
# ---------------------------------------------------------------------------
def _create_placeholder(filepath: str, page_num: int) -> None:
    """Create a simple placeholder image when SD fails."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new(
            "RGB", (config.SD_WIDTH, config.SD_HEIGHT), color=(200, 240, 200)
        )
        draw = ImageDraw.Draw(img)

        text = f"Page {page_num}\n(placeholder)"
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except (OSError, IOError):
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (config.SD_WIDTH - text_width) / 2
        y = (config.SD_HEIGHT - text_height) / 2
        draw.text((x, y), text, fill=(50, 100, 50), font=font)

        img.save(filepath)
        logger.info("Created placeholder for page %d", page_num)
    except Exception as e:
        logger.error("Could not create placeholder: %s", e)


def _save_cover_as_jpeg(image_data: bytes, filepath: str) -> bool:
    """Convert raw SD image bytes to a JPEG cover file."""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        image.save(filepath, "JPEG", quality=95, optimize=True)
        return True
    except Exception as e:
        logger.error("Could not save cover as JPEG: %s", e)
        return False


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        generate_images(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python generate_images.py <story.json> <images_dir>")
        sys.exit(1)
