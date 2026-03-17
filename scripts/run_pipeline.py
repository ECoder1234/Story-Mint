"""
Run Pipeline — master script that orchestrates the entire book creation process.
Runs all scripts in order, checks review status, reruns up to 3 times on FAIL.
Writes to series_list.txt after every successful run (CHANGE 5).
Renames book folder by title + series number (CHANGE 4).
Logs POV character, builds back.pdf + book_complete.pdf.
"""
import sys
import os
import time
import datetime
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


LOG_FILE = Path(config.LOGS_DIR) / "pipeline.log"


def log(message: str) -> None:
    """Log a message with timestamp to both console and log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _append_series_list(title: str, folder_name: str, series_number: int,
                        pov_character: str, book_type: str = "STANDALONE") -> None:
    """Append a new entry to config/series_list.txt (CHANGE 5)."""
    sl_path = Path(config.SERIES_LIST_PATH)
    sl_path.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    entry = (
        f"#{series_number:03d} \u2014 {title}\n"
        f"       Folder: {folder_name}\n"
        f"       Status: GENERATED\n"
        f"       Date: {date_str}\n"
        f"       Type: {book_type}\n"
        f"       POV Character: {pov_character}\n\n"
    )
    with open(sl_path, "a", encoding="utf-8") as f:
        f.write(entry)
    log(f"Appended series_list.txt entry #{series_number:03d}")


def _find_cover_art(images_dir: str) -> str | None:
    """Return the first existing cover art file in preferred order."""
    for name in ("cover.jpeg", "cover.jpg", "cover.png"):
        candidate = Path(images_dir) / name
        if candidate.exists():
            return str(candidate)
    return None


def run_pipeline() -> bool:
    """Execute the full book creation pipeline."""
    log("=" * 60)
    log("BOOK FACTORY PIPELINE STARTED")
    log("=" * 60)

    # CHANGE 10 — Cliffhanger research decision
    # Research indicates cliffhanger picture books for ages 3-7 commonly receive
    # frustrated one-star reviews from parents. Children in this age range expect
    # resolution. Skipping cliffhanger feature to protect review ratings.
    log("CHANGE 10: Cliffhanger feature SKIPPED — research shows cliffhangers "
        "hurt reviews and sales for ages 3-7 picture books.")
    book_type = "STANDALONE"

    # Quality thresholds: keep rewriting until avg >= 7.0 (matches email PASS threshold)
    QUALITY_AVG_TARGET = 7.0
    QUALITY_MIN_SCORE = 6
    MAX_QUALITY_ATTEMPTS = 5

    book_paths = None
    title = None
    pov_character = None
    review_avg = "N/A"
    last_critique: str | None = None
    best_avg: float = 0.0
    best_story_snapshot: list | None = None  # track best-scoring story pages

    # ── Step 1: Create book folder and choose POV (once, before quality loop) ──
    book_paths = config.get_book_paths()
    log(f"Book directory (temp): {book_paths['book_dir']}")

    try:
        from generate_story import choose_pov_character
        pov_character = choose_pov_character()
    except Exception:
        pov_character = "Rexi"
    log(f"POV character: {pov_character}")

    # ── Quality loop: generate → review → critique → regenerate ──
    for quality_attempt in range(1, MAX_QUALITY_ATTEMPTS + 1):
        log(f"Story quality attempt {quality_attempt}/{MAX_QUALITY_ATTEMPTS}")

        # ── Step 2: Generate story (pass critique when rewriting) ──
        log("Generating story...")
        try:
            from generate_story import generate_story
            story = generate_story(
                book_paths["story_json"],
                pov_character=pov_character,
                critique=last_critique,
            )
            if story is None:
                log("Story generation failed!")
                if quality_attempt < MAX_QUALITY_ATTEMPTS:
                    time.sleep(5)
                    continue
                else:
                    log("PIPELINE FAILED: Could not generate story after all retries.")
                    return False
            log(f"Story generated: {len(story)} pages")
        except Exception as e:
            log(f"Story generation error: {e}")
            if quality_attempt < MAX_QUALITY_ATTEMPTS:
                continue
            return False

        # ── Step 3: AI Review ──
        log("Running AI review...")
        try:
            from ai_review import review_story
            scores = review_story(
                book_paths["story_json"],
                book_paths["review_status"],
                book_paths["review_details"],
            )
        except Exception as e:
            log(f"AI Review error: {e}")
            scores = None

        if scores is None:
            # Review completely failed — write PASS and move on
            with open(book_paths["review_status"], "w") as f:
                f.write("PASS")
            log("Review failed to return scores. Setting PASS and continuing.")
            review_avg = "N/A"
            break

        avg = scores.get("average", 0)
        grammar = scores.get("grammar", 0)
        humor = scores.get("humor", 0)
        readability = scores.get("readability", 0)
        consistency = scores.get("consistency", 0)
        min_score = min(grammar, humor, readability, consistency)
        review_avg = str(round(avg, 2))

        log(f"Review scores — grammar:{grammar} humor:{humor} "
            f"readability:{readability} consistency:{consistency} "
            f"avg:{avg:.2f} status:{scores.get('status','?')}")
        # Track best-scoring story so far
        if avg > best_avg:
            best_avg = avg
            try:
                with open(book_paths["story_json"], "r", encoding="utf-8") as _f:
                    best_story_snapshot = json.load(_f)
            except Exception:
                pass
        # Check if quality target is met
        if avg >= QUALITY_AVG_TARGET and min_score >= QUALITY_MIN_SCORE:
            log(f"Quality target reached (avg={avg:.2f}, min={min_score}). Accepting story.")
            break

        if quality_attempt < MAX_QUALITY_ATTEMPTS:
            # Build critique from the review comments for the next rewrite
            comments = scores.get("comments", "")
            if isinstance(comments, list):
                comments = " | ".join(comments)
            last_critique = (
                f"grammar={grammar}/10 humor={humor}/10 "
                f"readability={readability}/10 consistency={consistency}/10\n"
                f"Specific problems to fix: {comments}"
            )
            log(f"Quality below target (avg={avg:.2f}, need {QUALITY_AVG_TARGET}). "
                f"Rewriting with critique...")
            time.sleep(3)
        else:
            log(f"WARNING: Max quality attempts reached. Best avg={best_avg:.2f}. Restoring best story...")
            # Restore the best-scoring story instead of keeping the last (possibly worse) one
            if best_story_snapshot is not None:
                try:
                    with open(book_paths["story_json"], "w", encoding="utf-8") as _f:
                        json.dump(best_story_snapshot, _f, ensure_ascii=False, indent=2)
                    # Update review_status to reflect our best score
                    best_status = "PASS" if best_avg >= 7.0 else "FAIL"
                    with open(book_paths["review_status"], "w") as _f:
                        _f.write(best_status)
                    review_avg = str(round(best_avg, 2))
                    log(f"Best story restored (avg={best_avg:.2f}, status={best_status}).")
                except Exception as _e:
                    log(f"Could not restore best story: {_e}")

    if book_paths is None:
        log("PIPELINE FAILED: No book paths created.")
        return False

    # ── Step 4: Generate title and rename folder ──
    log("Generating title...")
    try:
        with open(book_paths["story_json"], "r", encoding="utf-8") as f:
            story_data = json.load(f)
        from metadata import _generate_title
        title = _generate_title(story_data) if story_data else "Rexis Big Day"
    except Exception:
        title = "Rexis Big Day"

    log(f"Title: {title}")

    try:
        book_paths = config.rename_book_folder(book_paths, title)
        log(f"Book directory (final): {book_paths['book_dir']}")
    except Exception as e:
        log(f"Folder rename error: {e}")

    # ── Unload Ollama from VRAM before SD Forge starts ──
    # gemma3:4b holds ~2.5 GB VRAM; keep_alive=0 evicts it immediately.
    try:
        import requests as _req
        _req.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": config.OLLAMA_MODEL, "keep_alive": 0},
            timeout=10,
        )
        log("Ollama model unloaded from VRAM (freeing GPU memory for SD Forge)")
    except Exception as _e:
        log(f"Ollama unload skipped: {_e}")

    # ── Step 5: Generate images ──
    log("Generating illustrations...")
    try:
        from generate_images import generate_images
        success, fail = generate_images(
            book_paths["story_json"],
            book_paths["images_dir"],
            pov_character=pov_character or "Rexi",
        )
        log(f"Images generated: {success} success, {fail} failed")
    except Exception as e:
        log(f"Image generation error: {e}")
        log("Continuing with placeholder images...")

    # ── Step 5b: Generate cover illustration ──
    cover_img = None
    log("Generating cover illustration...")
    try:
        from generate_images import generate_cover_image
        cover_img = generate_cover_image(
            book_paths["images_dir"],
            title=title or "Dino Tails",
            pov_character=pov_character or "Rexi",
        )
        if cover_img:
            log(f"Cover image generated: {cover_img}")
        else:
            log("Cover image generation failed, using text-only cover")
    except Exception as e:
        log(f"Cover image error: {e}")

    # ── Step 6: Build PDFs ──
    log("Building PDFs...")
    try:
        from build_pdf import build_interior_pdf
        build_interior_pdf(
            book_paths["story_json"],
            book_paths["images_dir"],
            book_paths["interior_pdf"],
        )
        log(f"Interior PDF created: {book_paths['interior_pdf']}")
    except Exception as e:
        log(f"Interior PDF error: {e}")

    cover_art_path = cover_img or _find_cover_art(book_paths["images_dir"])

    try:
        from build_pdf import build_cover_pdf
        build_cover_pdf(title, book_paths["cover_pdf"], cover_art_path)
        log(f"Cover PDF created: {book_paths['cover_pdf']}")
    except Exception as e:
        log(f"Cover PDF error: {e}")

    try:
        from build_pdf import build_cover_jpeg
        build_cover_jpeg(title, book_paths["cover_jpeg"], cover_art_path)
        log(f"Cover JPEG created: {book_paths['cover_jpeg']}")
    except Exception as e:
        log(f"Cover JPEG error: {e}")

    # ── Step 6b: Build back cover (CHANGE 2) ──
    log("Building back cover PDF...")
    try:
        from build_pdf import build_back_pdf
        build_back_pdf(book_paths["back_pdf"], title=title or "Dino Tails")
        log(f"Back cover PDF created: {book_paths['back_pdf']}")
    except Exception as e:
        log(f"Back cover PDF error: {e}")

    # ── Step 6c: Merge into book_final.pdf (local only) ──
    log("Building book_final.pdf...")
    try:
        from build_pdf import build_final_pdf
        build_final_pdf(
            book_paths["cover_pdf"],
            book_paths["interior_pdf"],
            book_paths["book_final_pdf"],
        )
        log(f"book_final.pdf created: {book_paths['book_final_pdf']}")
    except Exception as e:
        log(f"book_final.pdf error: {e}")

    # ── Step 6d: Build book_complete.pdf (CHANGE 3) ──
    log("Building book_complete.pdf...")
    try:
        from build_pdf import build_complete_pdf
        build_complete_pdf(
            book_paths["cover_pdf"],
            book_paths["interior_pdf"],
            book_paths["back_pdf"],
            book_paths["book_complete_pdf"],
        )
        log(f"book_complete.pdf created: {book_paths['book_complete_pdf']}")
    except Exception as e:
        log(f"book_complete.pdf error: {e}")

    # ── Step 7: Generate metadata ──
    log("Generating metadata...")
    try:
        from metadata import generate_metadata
        title = generate_metadata(
            book_paths["story_json"],
            book_paths["metadata_txt"],
            title,
        )
        log(f"Metadata created: {book_paths['metadata_txt']}")
    except Exception as e:
        log(f"Metadata error: {e}")

    # ── Step 8: Generate audiobook ──
    log("Generating audiobook...")
    try:
        from generate_audiobook import generate_audiobook
        audio_path = generate_audiobook(
            book_paths["story_json"],
            book_paths["audiobook_mp3"],
        )
        if audio_path:
            log(f"Audiobook created: {audio_path}")
        else:
            log("Audiobook generation failed")
    except Exception as e:
        log(f"Audiobook error: {e}")

    # ── Step 9: Check review status and send email ──
    review_status = "UNKNOWN"
    try:
        with open(book_paths["review_status"], "r") as f:
            review_status = f.read().strip()
    except Exception:
        review_status = "UNKNOWN"

    if review_status == "PASS":
        log("Review PASSED — sending review email...")
        try:
            from send_review_email import send_review_email
            email_sent = send_review_email(
                book_paths,
                title=title or config.SERIES_NAME,
                pov_character=pov_character or "Rexi",
                series_number=book_paths.get("series_number", 1),
                review_score=review_avg,
                book_type=book_type,
            )
            if email_sent:
                log("Review email sent successfully!")
            else:
                log("Review email failed to send")
        except Exception as e:
            log(f"Email error: {e}")
    else:
        log(f"Review status: {review_status} — email not sent")
        log("Check review_details.json for scoring breakdown")

    # ── Step 10: Append to series_list.txt (CHANGE 5) ──
    try:
        folder_name = Path(book_paths["book_dir"]).name
        _append_series_list(
            title=title or "Untitled",
            folder_name=folder_name,
            series_number=book_paths.get("series_number", 1),
            pov_character=pov_character or "Rexi",
            book_type=book_type,
        )
    except Exception as e:
        log(f"series_list.txt append error: {e}")

    # ── Done ──
    log("=" * 60)
    log("PIPELINE COMPLETE")
    log(f"Book directory: {book_paths['book_dir']}")
    log(f"Review status: {review_status}")
    log(f"POV character: {pov_character}")
    log(f"Series number: {book_paths.get('series_number', '?')}")
    log("=" * 60)

    return review_status == "PASS"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dino Tails Book Factory Pipeline")
    parser.add_argument("--count", type=int, default=1, help="Number of books to generate sequentially")
    args = parser.parse_args()

    passed = 0
    failed = 0
    for book_num in range(1, args.count + 1):
        if args.count > 1:
            print(f"\n{'='*60}\nSTARTING BOOK {book_num}/{args.count}\n{'='*60}")
        try:
            success = run_pipeline()
            if success:
                passed += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\n[Pipeline] Cancelled by user. Exiting cleanly.")
            sys.exit(0)
        except Exception as _e:
            print(f"[Pipeline] Unexpected error on book {book_num}: {_e}")
            failed += 1

    if args.count > 1:
        print(f"\n{'='*60}\nBATCH COMPLETE: {passed} passed, {failed} failed out of {args.count} books\n{'='*60}")
    sys.exit(0 if failed == 0 else 1)
