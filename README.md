# Book Factory — Open Source Pipeline

> Generate illustrated 24-page children's books using AI — locally, privately, for free.

**One prompt → full illustrated PDF book.**

This is the open-source core pipeline from **StoryMint** by **Ervin Ezzati Jivan**. It runs entirely on your local machine with Ollama (text) and Stable Diffusion Forge (illustrations).

---

## What it does

1. You provide a story idea
2. The pipeline validates the prompt
3. Writes a 24-page story with comedic structure
4. AI reviews and rewrites until quality passes
5. Generates an illustration for every page
6. Builds cover + interior + back cover PDFs
7. Packages everything into a ZIP ready for publishing

---

## Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.11+ | Runtime |
| [Ollama](https://ollama.com) | Latest | Story writing + review AI |
| [SD Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) | Latest | Illustrations |

### Ollama models

```bash
ollama pull gemma3:4b    # recommended
ollama pull gemma3:1b    # lighter alternative
```

### SD model

[ToonYou Beta 6](https://civitai.com/models/30240/toonyou) — place `.safetensors` in your SD Forge models folder.

---

## Setup

```bash
# Clone
git clone https://github.com/ecoder1234/book-factory-open-source.git
cd book-factory-open-source

# Virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Ollama
ollama serve

# Start SD Forge (in another terminal)
cd /path/to/stable-diffusion-webui-forge
./webui-user.bat   # Windows
# ./webui.sh       # Linux
```

---

## Usage

```bash
python scripts/run_pipeline.py
```

Or from Python:

```python
from scripts.run_pipeline import run_pipeline

result = run_pipeline(
    user_prompt="A tiny robot who is afraid of the dark but discovers fireflies",
    author_name="Your Name",
    art_style="cartoon",
)

print(result["zip_path"])  # path to the finished book_package.zip
```

---

## Configuration

Edit `scripts/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OLLAMA_MODEL` | `gemma3:4b` | LLM for story + review |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `SD_MODEL` | `toonyou_beta6` | Stable Diffusion model |
| `STABLE_DIFFUSION_URL` | `http://localhost:7860` | SD Forge API URL |
| `SD_STEPS` | `28` | Diffusion steps |
| `NUM_PAGES` | `24` | Pages per book |

---

## Illustration Styles

| Style | Description |
|-------|-------------|
| `cartoon` | Flat colors, bold outlines (default) |
| `watercolor` | Soft, painterly look |
| `sketch` | Pencil with color wash |
| `pixel` | Retro 8-bit |
| `flat` | Minimal vector look |

---

## Output

Each book generates a `book_package.zip` containing:

| File | Description |
|------|-------------|
| `cover.pdf` | Print-ready front cover |
| `cover.jpg` | 2550×2550 px cover image |
| `interior.pdf` | 24 illustrated pages |
| `full-book.pdf` | Cover + interior + back |

---

## StoryMint

The commercial version with web UI, subscription plans, cloud storage, and more: [github.com/ecoder1234/book-factory-open-source](https://github.com/ecoder1234/book-factory-open-source)

---

## License

MIT — use freely for personal or commercial children's books.

(c) Ervin Ezzati Jivan
