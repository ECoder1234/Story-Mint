"""
Book Factory Configuration
All settings, paths, URLs, email recipients, SD/Ollama parameters.
Folder naming uses title + series_counter.txt (3-digit padded).
"""
import re
from pathlib import Path

# ================================================================
# BASE PATHS
# ================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
BOOKS_DIR = BASE_DIR / "books"
LOGS_DIR = BASE_DIR / "logs"
TEMPLATES_DIR = BASE_DIR / "templates"
APPROVED_DIR = BASE_DIR / "approved"
EXPORTS_DIR = BASE_DIR / "exports"
CONFIG_DIR = BASE_DIR / "config"

# ================================================================
# EMAIL SETTINGS
# ================================================================
PRIMARY_REVIEWER = "ervinjivan@gmail.com"
ADDITIONAL_REVIEWERS = ["mersi1112@gmail.com", "Lily.jivan@gmail.com"]
ALL_REVIEWERS = [PRIMARY_REVIEWER] + ADDITIONAL_REVIEWERS

# ================================================================
# NGROK / SERVICE URLs
# ================================================================
NGROK_URLS_FILE = CONFIG_DIR / "ngrok_urls.txt"

STABLE_DIFFUSION_URL = "http://localhost:7860"
OLLAMA_URL = "http://localhost:11434"


def load_ngrok_urls() -> None:
    """Read ngrok URLs from config file and update globals."""
    global STABLE_DIFFUSION_URL, OLLAMA_URL
    if NGROK_URLS_FILE.exists():
        for line in NGROK_URLS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("STABLE_DIFFUSION_URL="):
                STABLE_DIFFUSION_URL = line.split("=", 1)[1]
            elif line.startswith("OLLAMA_URL="):
                OLLAMA_URL = line.split("=", 1)[1]


# Auto-load on import
load_ngrok_urls()

# ================================================================
# AI SETTINGS
# ================================================================
OLLAMA_MODEL = "gemma3:4b"
SD_STEPS = 28
SD_WIDTH = 768
SD_HEIGHT = 768
SD_COVER_SIZE = 1024  # cover generates at higher resolution than interior pages
SD_SEED = 42
# Model name without extension — switch here to change active model
# DreamShaper_8_pruned  = good general model (installed, active now)
# toonyou_beta6         = best for children's storybook cartoon style
#   → download from https://civitai.com/models/30240/toonyou
#   → place in sd-forge/models/Stable-diffusion/ then change line below
SD_MODEL = "toonyou_beta6"

# ================================================================
# BOOK SETTINGS
# ================================================================
NUM_PAGES = 24
SERIES_NAME = "Dino Tails"

# ================================================================
# WORLD BIBLE
# ================================================================
BOOK_CONTEXT_PATH = CONFIG_DIR / "book_context.md"
SERIES_COUNTER_PATH = CONFIG_DIR / "series_counter.txt"
SERIES_LIST_PATH = CONFIG_DIR / "series_list.txt"

# ================================================================
# N8N SETTINGS (remote server — used for Gmail sending)
# ================================================================
N8N_BASE_URL = "https://sociplus.com/n8n"
N8N_WEBHOOK_URL = N8N_BASE_URL + "/webhook/dino-tails-email"
N8N_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1MGE2MzQyYy1iZTcyLTQ2ODUtOWUyNC05MGU1YjAyNWU0NzUiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwiaWF0IjoxNzczMzYzNTI2fQ.1QmWRx68WMvAtKWZtyQJx2st9vctwl8eXwiQWHzeI0g"

# ================================================================
# POV CHARACTERS (rotation order)
# ================================================================
POV_CHARACTERS = ["Rexi", "Lonnie", "Pterry", "Spike", "Mara"]


# ================================================================
# SERIES COUNTER HELPERS
# ================================================================
def _read_series_counter() -> int:
    """Read current series counter, starting at 1 if file missing."""
    try:
        return int(SERIES_COUNTER_PATH.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 1


def _write_series_counter(value: int) -> None:
    """Write counter back to file."""
    SERIES_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERIES_COUNTER_PATH.write_text(str(value), encoding="utf-8")


def _title_to_folder_name(title: str, number: int) -> str:
    """Convert title to folder-safe name with padded number."""
    safe = title.lower().strip()
    safe = re.sub(r"[^a-z0-9\s_]", "", safe)
    safe = re.sub(r"\s+", "_", safe).strip("_")
    if not safe:
        safe = "untitled"
    return f"{safe}_{number:03d}"


# ================================================================
# FILE PATHS (generated per book run)
# ================================================================
def get_book_paths(book_title: str | None = None) -> dict:
    """Return dict of all file paths for a book run.

    If *book_title* is not yet known, a temporary name is used.
    Call ``rename_book_folder()`` once the title is available.
    """
    series_number = _read_series_counter()

    if book_title:
        folder_name = _title_to_folder_name(book_title, series_number)
    else:
        folder_name = f"_temp_{series_number:03d}"

    book_dir = BOOKS_DIR / folder_name
    images_dir = book_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    return _paths_dict(book_dir, images_dir, series_number)


def rename_book_folder(old_paths: dict, title: str) -> dict:
    """Rename a temp book folder to its final title-based name.

    Increments the series counter and returns updated paths dict.
    """
    series_number = old_paths["series_number"]
    new_folder_name = _title_to_folder_name(title, series_number)
    new_book_dir = BOOKS_DIR / new_folder_name

    old_book_dir = Path(old_paths["book_dir"])
    if old_book_dir != new_book_dir and old_book_dir.exists():
        old_book_dir.rename(new_book_dir)

    # Increment counter for next run
    _write_series_counter(series_number + 1)

    images_dir = new_book_dir / "images"
    return _paths_dict(new_book_dir, images_dir, series_number)


def _paths_dict(book_dir: Path, images_dir: Path, series_number: int) -> dict:
    """Build the standard paths dictionary."""
    return {
        "book_dir": str(book_dir),
        "images_dir": str(images_dir),
        "story_json": str(book_dir / "story.json"),
        "review_status": str(book_dir / "review_status.txt"),
        "review_details": str(book_dir / "review_details.json"),
        "interior_pdf": str(book_dir / "interior.pdf"),
        "cover_pdf": str(book_dir / "cover.pdf"),
        "cover_jpeg": str(book_dir / "cover.jpg"),
        "back_pdf": str(book_dir / "back.pdf"),
        "metadata_txt": str(book_dir / "metadata.txt"),
        "cover_image": str(images_dir / "cover.jpg"),
        "book_final_pdf": str(book_dir / "book_final.pdf"),
        "book_complete_pdf": str(book_dir / "book_complete.pdf"),
        "book_package_zip": str(book_dir / "book_package.zip"),
        "audiobook_mp3": str(book_dir / "audiobook.mp3"),
        "series_number": series_number,
    }


if __name__ == "__main__":
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"OLLAMA_URL: {OLLAMA_URL}")
    print(f"STABLE_DIFFUSION_URL: {STABLE_DIFFUSION_URL}")
    print(f"ALL_REVIEWERS: {ALL_REVIEWERS}")
    print(f"SERIES_NAME: {SERIES_NAME}")
    print(f"N8N_WEBHOOK_URL: {N8N_WEBHOOK_URL}")
    paths = get_book_paths("Test Book Title")
    for k, v in paths.items():
        print(f"  {k}: {v}")
