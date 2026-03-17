"""
Build PDF — creates cover.pdf, back.pdf, interior.pdf, book_final.pdf,
and book_complete.pdf for KDP.
Interior: 8.5x8.5 inch, image top 80%, text bottom 20%, font 26.
Cover: illustration top 65%, dark green band bottom 35%, series name top,
       title centered in band, author below.
Back: dark green theme, description, barcode placeholder bottom-left.
book_complete.pdf = cover + interior + back merged.
"""
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

from reportlab.lib.pagesizes import inch
from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase.pdfmetrics import stringWidth


PAGE_SIZE = (8.5 * inch, 8.5 * inch)
MARGIN = 0.5 * inch
IMAGE_HEIGHT_RATIO = 0.80
TEXT_HEIGHT_RATIO = 0.20
PDF_IMAGE_MAX_PX = 768

# Cover colours
COVER_GREEN_DARK = HexColor("#1A3A10")
COVER_GREEN_BAND = HexColor("#1A3A10")
COVER_BORDER = HexColor("#2E5A1E")
SERIES_BAND_COLOR = Color(0.1, 0.22, 0.06, alpha=0.7)  # semi-transparent dark
COVER_BAND_RATIO = 0.38
COVER_SERIES_BAND_HEIGHT = 38
COVER_SERIES_FONT_SIZE = 15
COVER_TITLE_FONT_SIZE = 46
COVER_TITLE_LINE_GAP = 10
COVER_TITLE_BOTTOM_Y = 74
COVER_AUTHOR_FONT_SIZE = 17
COVER_AUTHOR_Y = 24


def _resize_image_for_pdf(img_path: str, max_size: int = PDF_IMAGE_MAX_PX) -> str:
    """Resize and JPEG-compress an image for PDF embedding using PIL."""
    try:
        from PIL import Image

        img = Image.open(img_path)
        img.thumbnail((max_size, max_size), Image.LANCZOS)

        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode == "P":
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        img.save(tmp.name, "JPEG", quality=85, optimize=True)
        return tmp.name
    except Exception:
        return img_path


# ──────────────────────────────────────────────────────────────────
# INTERIOR
# ──────────────────────────────────────────────────────────────────
def build_interior_pdf(story_json_path: str, images_dir: str, output_pdf_path: str) -> None:
    """Build the interior PDF with images top 80 %, text bottom 20 %."""

    with open(story_json_path, "r", encoding="utf-8") as f:
        story = json.load(f)

    page_w, page_h = PAGE_SIZE
    usable_w = page_w - 2 * MARGIN
    usable_h = page_h - 2 * MARGIN

    image_area_h = usable_h * IMAGE_HEIGHT_RATIO
    text_area_h = usable_h * TEXT_HEIGHT_RATIO

    c = pdfcanvas.Canvas(output_pdf_path, pagesize=PAGE_SIZE)
    tmp_files: list[str] = []

    try:
        for page_data in story:
            page_num = page_data["page"]
            text = page_data["text"]

            c.setFillColor(white)
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

            img_file = os.path.join(images_dir, f"page_{page_num:02d}.png")
            if os.path.exists(img_file):
                tmp_path = _resize_image_for_pdf(img_file)
                if tmp_path != img_file:
                    tmp_files.append(tmp_path)
                try:
                    c.drawImage(
                        tmp_path,
                        MARGIN,
                        MARGIN + text_area_h,
                        width=usable_w,
                        height=image_area_h,
                        preserveAspectRatio=False,
                    )
                except Exception as e:
                    print(f"[PDF] Warning: Could not draw image for page {page_num}: {e}")
                    _draw_placeholder_rect(c, MARGIN, MARGIN + text_area_h, usable_w, image_area_h, page_num)
            else:
                _draw_placeholder_rect(c, MARGIN, MARGIN + text_area_h, usable_w, image_area_h, page_num)

            # Text area
            c.setFillColor(white)
            c.rect(MARGIN, MARGIN, usable_w, text_area_h, fill=1, stroke=0)

            c.setFillColor(black)
            lines = _wrap_text(text, "Helvetica", 26, usable_w - 20)
            line_height = 32
            total_text_h = len(lines) * line_height
            start_y = MARGIN + text_area_h / 2 + total_text_h / 2 - line_height

            for i, line in enumerate(lines):
                y = start_y - i * line_height
                if y > MARGIN:
                    c.setFont("Helvetica", 26)
                    c.drawCentredString(page_w / 2, y, line)

            # Page number
            c.setFont("Helvetica", 11)
            c.setFillColor(HexColor("#999999"))
            c.drawCentredString(page_w / 2, MARGIN / 2, str(page_num))

            c.showPage()
    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass

    c.save()
    print(f"[PDF] Interior PDF saved: {output_pdf_path}")


# ──────────────────────────────────────────────────────────────────
# FRONT COVER  (CHANGE 1)
# ──────────────────────────────────────────────────────────────────
def build_cover_pdf(title: str, output_pdf_path: str, cover_image_path: str | None = None) -> None:
    """Build front cover: illustration fills FULL page, semi-transparent dark green
    band overlaid at bottom 35%, series name at top, title in band, Written by below."""
    page_w, page_h = PAGE_SIZE
    c = pdfcanvas.Canvas(output_pdf_path, pagesize=PAGE_SIZE)
    tmp_files: list[str] = []

    band_h = page_h * COVER_BAND_RATIO
    series_band_h = COVER_SERIES_BAND_HEIGHT
    cover_image_path = _resolve_cover_image_path(cover_image_path)

    try:
        # ---------- Illustration fills the ENTIRE page ----------
        if cover_image_path and os.path.exists(cover_image_path):
            tmp_cover = _resize_image_for_pdf(cover_image_path, max_size=900)
            if tmp_cover != cover_image_path:
                tmp_files.append(tmp_cover)
            try:
                c.drawImage(
                    tmp_cover,
                    0, 0,
                    width=page_w,
                    height=page_h,
                    preserveAspectRatio=False,
                )
            except Exception:
                _draw_gradient_green(c, 0, 0, page_w, page_h)
        else:
            _draw_gradient_green(c, 0, 0, page_w, page_h)

        # ---------- Series name band at very top — semi-transparent overlay ----------
        c.saveState()
        c.setFillColor(Color(0.08, 0.20, 0.04, alpha=0.72))
        c.rect(0, page_h - series_band_h, page_w, series_band_h, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Oblique", COVER_SERIES_FONT_SIZE)
        c.drawCentredString(page_w / 2, page_h - series_band_h + 13, "Dino Tails")
        c.restoreState()

        # ---------- Bottom text band — semi-transparent dark green overlay ----------
        c.saveState()
        c.setFillColor(Color(0.08, 0.20, 0.04, alpha=0.82))
        c.rect(0, 0, page_w, band_h, fill=1, stroke=0)
        c.restoreState()

        # ---------- Thin decorative line at top of band ----------
        c.saveState()
        c.setStrokeColor(Color(0.55, 0.85, 0.35, alpha=0.7))
        c.setLineWidth(2)
        c.line(MARGIN, band_h, page_w - MARGIN, band_h)
        c.restoreState()

        # ---------- Title text centred in band ----------
        c.setFillColor(white)
        title_font_size = COVER_TITLE_FONT_SIZE
        title_lines = _wrap_text(title, "Helvetica-Bold", title_font_size, page_w - 2 * inch)
        line_h = title_font_size + COVER_TITLE_LINE_GAP

        # Keep the full text block anchored lower so it stays inside the
        # translucent green band even when the title wraps to multiple lines.
        author_y = COVER_AUTHOR_Y
        title_bottom_y = COVER_TITLE_BOTTOM_Y
        title_start_y = title_bottom_y + (len(title_lines) - 1) * line_h

        for i, line in enumerate(title_lines):
            c.setFont("Helvetica-Bold", title_font_size)
            c.drawCentredString(page_w / 2, title_start_y - i * line_h, line)

        # ---------- Written by line ----------
        c.setFont("Helvetica-Oblique", COVER_AUTHOR_FONT_SIZE)
        c.setFillColor(HexColor("#CCEECC"))
        c.drawCentredString(page_w / 2, author_y, "Written by Ervin Ezzati Jivan")

    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass

    c.showPage()
    c.save()
    print(f"[PDF] Cover PDF saved: {output_pdf_path}")


def build_cover_jpeg(title: str, output_image_path: str, cover_image_path: str | None = None) -> None:
    """Build a finished front cover JPEG with the same layout as cover.pdf."""
    from PIL import Image, ImageDraw

    # KDP requires 300 DPI minimum for print. 8.5" × 300 = 2550 px.
    _COVER_PRINT_PX = 2550

    cover_image_path = _resolve_cover_image_path(cover_image_path)
    if cover_image_path and os.path.exists(cover_image_path):
        base = Image.open(cover_image_path).convert("RGB")
    else:
        base = _build_gradient_cover_image(config.SD_WIDTH, config.SD_HEIGHT)

    # Upscale to print resolution using high-quality Lanczos filter
    if base.width < _COVER_PRINT_PX or base.height < _COVER_PRINT_PX:
        base = base.resize((_COVER_PRINT_PX, _COVER_PRINT_PX), Image.LANCZOS)

    width, height = base.size
    scale = min(width / PAGE_SIZE[0], height / PAGE_SIZE[1])
    band_h = int(round(height * COVER_BAND_RATIO))
    band_top = height - band_h
    series_band_h = max(24, int(round(COVER_SERIES_BAND_HEIGHT * scale)))
    title_max_width = width - 2 * int(round(inch * scale))
    title_font_size = max(28, int(round(COVER_TITLE_FONT_SIZE * scale)))
    author_font_size = max(14, int(round(COVER_AUTHOR_FONT_SIZE * scale)))
    series_font_size = max(12, int(round(COVER_SERIES_FONT_SIZE * scale)))
    line_gap = max(6, int(round(COVER_TITLE_LINE_GAP * scale)))
    title_bottom_margin = max(42, int(round(COVER_TITLE_BOTTOM_Y * scale)))
    author_bottom_margin = max(14, int(round(COVER_AUTHOR_Y * scale)))
    band_inner_margin = max(18, int(round(18 * scale)))

    cover = base.convert("RGBA")
    overlay = Image.new("RGBA", cover.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 0, width, series_band_h), fill=(20, 51, 10, 184))
    overlay_draw.rectangle((0, band_top, width, height), fill=(20, 51, 10, 209))
    overlay_draw.line(
        (
            int(round(MARGIN * scale)),
            band_top,
            width - int(round(MARGIN * scale)),
            band_top,
        ),
        fill=(140, 217, 89, 178),
        width=max(2, int(round(2 * scale))),
    )
    cover = Image.alpha_composite(cover, overlay)
    draw = ImageDraw.Draw(cover)

    title_font, title_lines, line_h = _fit_cover_title(
        draw,
        title,
        height,
        band_top,
        band_inner_margin,
        title_font_size,
        title_max_width,
        line_gap,
        title_bottom_margin,
    )
    series_font = _load_cover_font(series_font_size, italic=True)
    author_font = _load_cover_font(author_font_size, italic=True)

    series_w, series_h = _measure_text(draw, "Dino Tails", series_font)
    draw.text(
        ((width - series_w) / 2, (series_band_h - series_h) / 2 - max(1, int(2 * scale))),
        "Dino Tails",
        fill=(255, 255, 255),
        font=series_font,
    )

    title_block_bottom = height - title_bottom_margin
    for i, line in enumerate(title_lines):
        text_w, text_h = _measure_text(draw, line, title_font)
        line_index_from_bottom = len(title_lines) - 1 - i
        y = title_block_bottom - text_h - (line_index_from_bottom * line_h)
        draw.text(((width - text_w) / 2, y), line, fill=(255, 255, 255), font=title_font)

    author_text = "Written by Ervin Ezzati Jivan"
    author_w, author_h = _measure_text(draw, author_text, author_font)
    draw.text(
        ((width - author_w) / 2, height - author_bottom_margin - author_h),
        author_text,
        fill=(204, 238, 204),
        font=author_font,
    )

    Path(output_image_path).parent.mkdir(parents=True, exist_ok=True)
    cover.convert("RGB").save(output_image_path, "JPEG", quality=95, optimize=True)
    print(f"[PDF] Cover JPEG saved: {output_image_path}")


# ──────────────────────────────────────────────────────────────────
# BACK COVER  (CHANGE 2)
# ──────────────────────────────────────────────────────────────────
def build_back_pdf(output_pdf_path: str, description: str = "", title: str = "") -> None:
    """Build back cover: dark green background, description, barcode placeholder."""
    page_w, page_h = PAGE_SIZE
    c = pdfcanvas.Canvas(output_pdf_path, pagesize=PAGE_SIZE)

    # Full dark green background
    c.setFillColor(COVER_GREEN_DARK)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    # Series name at top
    c.setFillColor(white)
    c.setFont("Helvetica-Oblique", 14)
    c.drawCentredString(page_w / 2, page_h - 0.7 * inch, "Dino Tails")

    # Description text centred in middle
    if not description:
        description = (
            f"Meet the wildest crew in Fernwood Valley! "
            f"In \"{title}\", laughs are guaranteed and tiny arms cause big problems. "
            f"A hilarious adventure for ages 3-7."
        )

    desc_lines = _wrap_text(description, "Helvetica", 16, page_w - 2.5 * inch)
    line_h = 22
    desc_start_y = page_h * 0.55 + (len(desc_lines) * line_h) / 2
    c.setFillColor(white)
    for i, line in enumerate(desc_lines):
        c.setFont("Helvetica", 16)
        c.drawCentredString(page_w / 2, desc_start_y - i * line_h, line)

    # Author name near bottom
    c.setFont("Helvetica", 14)
    c.setFillColor(HexColor("#CCEECC"))
    c.drawCentredString(page_w / 2, 1.8 * inch, "Ervin Ezzati Jivan")

    # Barcode placeholder — bottom left inside safe zone (per KDP Reference Image 3)
    barcode_x = MARGIN + 0.2 * inch
    barcode_y = MARGIN + 0.2 * inch
    barcode_w = 2.0 * inch
    barcode_h = 1.2 * inch

    c.setFillColor(white)
    c.rect(barcode_x, barcode_y, barcode_w, barcode_h, fill=1, stroke=0)
    c.setFillColor(HexColor("#AAAAAA"))
    c.setFont("Helvetica", 11)
    c.drawCentredString(barcode_x + barcode_w / 2, barcode_y + barcode_h / 2 - 5, "ISBN BARCODE")

    # Decorative dinosaur footprint in bottom-right corner
    _draw_dino_footprint(c, page_w - 1.2 * inch, MARGIN + 0.4 * inch, 0.5 * inch)

    c.showPage()
    c.save()
    print(f"[PDF] Back cover PDF saved: {output_pdf_path}")


# ──────────────────────────────────────────────────────────────────
# BOOK COMPLETE  (CHANGE 3)
# ──────────────────────────────────────────────────────────────────
def build_complete_pdf(cover_pdf_path: str, interior_pdf_path: str,
                       back_pdf_path: str, output_pdf_path: str) -> None:
    """Merge cover + interior + back into book_complete.pdf."""
    PdfReader, PdfWriter = _load_pdf_classes()
    writer = PdfWriter()

    for pdf_path in [cover_pdf_path, interior_pdf_path, back_pdf_path]:
        if os.path.exists(pdf_path):
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)
        else:
            print(f"[PDF] Warning: Missing {pdf_path} for complete merge")

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    print(f"[PDF] book_complete.pdf saved: {output_pdf_path}")


def build_final_pdf(cover_pdf_path: str, interior_pdf_path: str, output_pdf_path: str) -> None:
    """Merge cover.pdf + interior.pdf into book_final.pdf (local only)."""
    PdfReader, PdfWriter = _load_pdf_classes()
    writer = PdfWriter()

    for pdf_path in [cover_pdf_path, interior_pdf_path]:
        if os.path.exists(pdf_path):
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                writer.add_page(page)
        else:
            print(f"[PDF] Warning: Missing {pdf_path} for final merge")

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    print(f"[PDF] Final combined PDF saved: {output_pdf_path}")


# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────
def _resolve_cover_image_path(cover_image_path: str | None) -> str | None:
    """Find a usable cover image, supporting legacy PNG covers."""
    if not cover_image_path:
        return None
    if os.path.exists(cover_image_path):
        return cover_image_path

    path = Path(cover_image_path)
    for suffix in (".jpeg", ".jpg", ".png"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            return str(candidate)
    return None


def _load_cover_font(size: int, bold: bool = False, italic: bool = False):
    """Load a reasonable system font for cover rendering."""
    from PIL import ImageFont

    if bold and italic:
        candidates = ["arialbi.ttf", "DejaVuSans-BoldOblique.ttf", "DejaVuSans-Bold.ttf"]
    elif bold:
        candidates = ["arialbd.ttf", "DejaVuSans-Bold.ttf"]
    elif italic:
        candidates = ["ariali.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans.ttf"]
    else:
        candidates = ["arial.ttf", "DejaVuSans.ttf"]

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _measure_text(draw, text: str, font) -> tuple[int, int]:
    """Return rendered text width and height for PIL drawing."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text_pil(draw, text: str, font, max_width: int) -> list[str]:
    """Simple word-wrap for PIL text drawing."""
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        width, _ = _measure_text(draw, test_line, font)
        if width <= max_width or not current_line:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def _fit_cover_title(draw, title: str, height: int, band_top: int, band_inner_margin: int,
                     initial_size: int, max_width: int, line_gap: int,
                     title_bottom_margin: int) -> tuple[object, list[str], int]:
    """Shrink the title font until the wrapped block fits inside the bottom band."""
    font_size = initial_size

    while font_size >= 20:
        font = _load_cover_font(font_size, bold=True)
        line_h = font_size + line_gap
        lines = _wrap_text_pil(draw, title, font, max_width)
        title_block_bottom = height - title_bottom_margin
        top_of_block = title_block_bottom - line_h * len(lines)
        if top_of_block >= band_top + band_inner_margin:
            return font, lines, line_h
        font_size -= 2

    font = _load_cover_font(20, bold=True)
    return font, _wrap_text_pil(draw, title, font, max_width), 20 + line_gap


def _build_gradient_cover_image(width: int, height: int):
    """Create a green fallback background for cover JPEG output."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(77 + (140 - 77) * t)
        g = int(138 + (199 - 138) * t)
        b = int(51 + (97 - 51) * t)
        draw.line((0, y, width, y), fill=(r, g, b))
    return image


def _load_pdf_classes():
    """Import PDF reader/writer classes from whichever library is available."""
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        from pypdf import PdfReader, PdfWriter
    return PdfReader, PdfWriter


def _draw_gradient_green(c, x: float, y: float, w: float, h: float) -> None:
    """Fill area with a green gradient and faint footprint pattern."""
    steps = 20
    step_h = h / steps
    for i in range(steps):
        r = 0.30 + 0.25 * (i / steps)
        g = 0.55 + 0.25 * (i / steps)
        b = 0.20 + 0.15 * (i / steps)
        c.setFillColor(Color(r, g, b))
        c.rect(x, y + i * step_h, w, step_h + 1, fill=1, stroke=0)

    # Faint footprint pattern
    c.saveState()
    c.setFillColor(Color(0, 0, 0, alpha=0.06))
    for row in range(3):
        for col in range(4):
            fx = x + w * 0.15 + col * w * 0.22
            fy = y + h * 0.15 + row * h * 0.28
            _draw_dino_footprint(c, fx, fy, 0.35 * inch)
    c.restoreState()


def _draw_dino_footprint(c, cx: float, cy: float, size: float) -> None:
    """Draw a simple three-toed dinosaur footprint."""
    # Main pad
    c.circle(cx, cy, size * 0.35, fill=1, stroke=0)
    # Three toes
    for angle_offset in [-0.35, 0, 0.35]:
        import math
        tx = cx + math.sin(angle_offset) * size * 0.6
        ty = cy + math.cos(angle_offset) * size * 0.6
        c.circle(tx, ty, size * 0.15, fill=1, stroke=0)


def _draw_placeholder_rect(c, x: float, y: float, w: float, h: float, page_num: int) -> None:
    """Draw a green placeholder rectangle when no image is available."""
    c.setFillColor(HexColor("#C8E6C9"))
    c.rect(x, y, w, h, fill=1, stroke=1)
    c.setFillColor(HexColor("#4CAF50"))
    c.setFont("Helvetica", 20)
    c.drawCentredString(x + w / 2, y + h / 2, f"[Illustration — Page {page_num}]")


def _wrap_text(text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    """Simple word wrap for ReportLab canvas text."""
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        width = stringWidth(test_line, font_name, font_size)
        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        story_path = sys.argv[1]
        images_path = sys.argv[2]
        interior_out = sys.argv[3]
        cover_out = sys.argv[4] if len(sys.argv) > 4 else interior_out.replace("interior", "cover")
        cover_img = sys.argv[5] if len(sys.argv) > 5 else None

        build_interior_pdf(story_path, images_path, interior_out)
        build_cover_pdf("Dino Tails", cover_out, cover_img)
    else:
        print("Usage: python build_pdf.py <story.json> <images_dir> <interior.pdf> [cover.pdf] [cover.jpeg]")
        sys.exit(1)
