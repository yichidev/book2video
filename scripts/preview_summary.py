"""
Preview the vocabulary summary frame as a PNG without generating video.
Usage: python preview_summary.py output/A1_A_1/text/A1_A_1_de_en.json
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

JSON_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/A1_A_1/text/A1_A_1_de_en.json")
OUT_PATH = Path("preview_summary.png")

W, H = 1920, 1080
PADDING = 60
COL_GAP = 70
MIN_FONT_SIZE = 28
FONT_STEP = 4


def _pos_key(lemma: str, source_word: str) -> int:
    if lemma and lemma[0].isupper():
        return 0  # noun
    if source_word.endswith(("en", "ern")) or "(sich)" in source_word:
        return 2  # verb
    return 1  # adjective / other


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


with open(JSON_PATH) as f:
    data = json.load(f)

entries = [
    (lemma, v["source_word"], v["target_word"])
    for lemma, v in data.items()
    if v.get("target_word", "").strip()
]
entries.sort(key=lambda x: _pos_key(x[0], x[1]))

pairs = [f"{source}  ·  {target}" for _, source, target in entries]

bg = Image.open("input/assets/background.png").resize((W, H), Image.LANCZOS)
draw = ImageDraw.Draw(bg)


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1] + 8


font_size = 40
font = _load_font(font_size)
line_h = _line_height(font)
total_h = line_h * len(pairs)

if total_h > H - PADDING * 2:
    # 2-column — reduce font size until it fits
    mid = len(pairs) // 2
    col1_pairs, col2_pairs = pairs[:mid], pairs[mid:]
    while font_size >= MIN_FONT_SIZE:
        font = _load_font(font_size)
        line_h = _line_height(font)
        col1_h = line_h * len(col1_pairs)
        col2_h = line_h * len(col2_pairs)
        if max(col1_h, col2_h) <= H - PADDING * 2 or font_size == MIN_FONT_SIZE:
            break
        font_size -= FONT_STEP

    col1_w = max(draw.textlength(line, font=font) for line in col1_pairs)
    col2_w = max(draw.textlength(line, font=font) for line in col2_pairs)
    total_w = col1_w + COL_GAP + col2_w
    x1 = int((W - total_w) // 2)
    x2 = int(x1 + col1_w + COL_GAP)

    y1 = (H - line_h * len(col1_pairs)) // 2
    y2 = (H - line_h * len(col2_pairs)) // 2
    for i, line in enumerate(col1_pairs):
        draw.text((x1, y1 + i * line_h), line, font=font, fill="black")
    for i, line in enumerate(col2_pairs):
        draw.text((x2, y2 + i * line_h), line, font=font, fill="black")
    layout = f"2-column (font {font_size}pt)"
else:
    y = (H - total_h) // 2
    for i, line in enumerate(pairs):
        w_line = draw.textlength(line, font=font)
        x = int((W - w_line) // 2)
        draw.text((x, y + i * line_h), line, font=font, fill="black")
    layout = f"1-column (font {font_size}pt)"

bg.save(str(OUT_PATH))
print(f"Saved {OUT_PATH}  ({len(pairs)} words, {layout})")
