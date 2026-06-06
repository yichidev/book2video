"""
Quick preview script: renders the cover letter overlay and opens the result.
Usage:
    python scripts/preview_cover.py A1_B_1
    python scripts/preview_cover.py A1_C_D
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

FONT_PATH = "/System/Library/Fonts/Supplemental/Georgia.ttf"
BACKGROUND_PATH = Path("input/assets/background.png")


def _cover_labels(collection: str) -> tuple[str, str | None]:
    """Return (main_label, sub_label) for the cover overlay.

    Examples:
        A1_B_1  → ("B",     "Part 1")
        A1_C_D  → ("C & D", None)
        A1_A_2  → ("A",     "Part 2")
    """
    parts = collection.split("_")[1:]
    letters = [p for p in parts if not p.isdigit()]
    numbers = [p for p in parts if p.isdigit()]
    main = " & ".join(letters)
    sub = (f"Part {numbers[0]}" if len(numbers) == 1
           else ("Part " + ", ".join(numbers)) if numbers else None)
    return main, sub


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size=size)
    except Exception:
        return ImageFont.load_default()


def _centered_x(draw, text, font, w):
    bbox = draw.textbbox((0, 0), text, font=font)
    # subtract bbox[0] to correct for left bearing offset
    return (w - (bbox[2] - bbox[0])) // 2 - bbox[0]


def draw_cover_overlay(img: Image.Image, collection: str, w: int, h: int) -> Image.Image:
    """Draw full cover text layout on a clean background image."""
    cover_prefix = collection.split("_")[0]
    main, sub = _cover_labels(collection)

    # Book/level label e.g. "Goethe-Zertifikat A1"
    level_line1 = f"Goethe-Zertifikat {cover_prefix}"
    level_line2 = "Deutsch-Englisch Wortliste"

    draw = ImageDraw.Draw(img)

    font_main  = _load_font(340)   # big section letter(s)
    font_sub   = _load_font(55)    # "Part 1"
    font_info1 = _load_font(65)    # "Goethe-Zertifikat A1"
    font_info2 = _load_font(45)    # "Deutsch-Englisch Wortliste"

    ink       = (35, 35, 35, 230)
    ink_light = (80, 80, 80, 200)

    # ── layout zones (fixed anchors, so nothing ever gets squeezed) ─────────
    # Zone A: section letter  — top third  (y = 80 … h*0.45)
    # Zone B: "Part N"        — just below letter, minimum 60 px clear
    # Zone C: Goethe info     — bottom, pinned from h upward

    bbox_main = draw.textbbox((0, 0), main, font=font_main)
    main_h = bbox_main[3] - bbox_main[1]

    bbox_sub = draw.textbbox((0, 0), sub, font=font_sub) if sub else None
    sub_h = (bbox_sub[3] - bbox_sub[1]) if bbox_sub else 0
    GAP_MAIN_SUB = 100

    # Goethe info pinned to bottom
    bbox1 = draw.textbbox((0, 0), level_line1, font=font_info1)
    bbox2 = draw.textbbox((0, 0), level_line2, font=font_info2)
    info1_h = bbox1[3] - bbox1[1]
    info2_h = bbox2[3] - bbox2[1]
    INFO_LINE_GAP = 15
    BOTTOM_PAD = 110 # to move the Goethe block up, increase it
    y_info2 = h - BOTTOM_PAD - info2_h
    y_info1 = y_info2 - INFO_LINE_GAP - info1_h

    # Center the B + Part1 block in the full image height
    y_main = (h - main_h) // 2 - 110
    # increase the offset to everything up more
    draw.text((_centered_x(draw, main, font_main, w), y_main),
              main, font=font_main, fill=ink)

    y_sub_start = y_main + main_h + GAP_MAIN_SUB
    if sub:
        draw.text((_centered_x(draw, sub, font_sub, w), y_sub_start),
                  sub, font=font_sub, fill=ink_light)
    draw.text((_centered_x(draw, level_line1, font_info1, w), y_info1),
              level_line1, font=font_info1, fill=ink_light)
    draw.text((_centered_x(draw, level_line2, font_info2, w), y_info2),
              level_line2, font=font_info2, fill=ink_light)

    return img


def preview_cover(collection: str) -> Path:
    with Image.open(BACKGROUND_PATH) as _img:
        img = _img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS).convert("RGBA")

    img = draw_cover_overlay(img, collection, VIDEO_WIDTH, VIDEO_HEIGHT)

    out = Path(f"/tmp/cover_preview_{collection}.png")
    img.convert("RGB").save(str(out))
    print(f"Saved: {out}")
    return out


if __name__ == "__main__":
    collection = sys.argv[1] if len(sys.argv) > 1 else "A1_B_1"
    out = preview_cover(collection)
    import subprocess
    subprocess.run(["open", str(out)])
