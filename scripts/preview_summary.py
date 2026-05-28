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
FONT_SIZE = 40
PADDING = 60
COL_GAP = 70


def _pos_key(lemma: str, german_word: str) -> int:
    if lemma and lemma[0].isupper():
        return 0  # noun
    if german_word.endswith(("en", "ern")) or "(sich)" in german_word:
        return 2  # verb
    return 1  # adjective / other


with open(JSON_PATH) as f:
    data = json.load(f)

entries = [
    (lemma, v["german_word"], v["translated_word"])
    for lemma, v in data.items()
    if v.get("translated_word", "").strip()
]
entries.sort(key=lambda x: _pos_key(x[0], x[1]))

pairs = [f"{german}  ·  {translated}" for _, german, translated in entries]

bg = Image.open("input/assets/background.png").resize((W, H), Image.LANCZOS)
draw = ImageDraw.Draw(bg)

# Try to load the same font moviepy uses; fall back to default
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans.ttf", FONT_SIZE)
except Exception:
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

# Measure line height
sample_bbox = draw.textbbox((0, 0), "Ag", font=font)
line_h = sample_bbox[3] - sample_bbox[1] + 8

total_h = line_h * len(pairs)

if total_h > H - PADDING * 2:
    # 2-column layout — centered as a unit
    mid = len(pairs) // 2
    col1, col2 = pairs[:mid], pairs[mid:]
    col1_h = line_h * len(col1)
    col2_h = line_h * len(col2)

    # Measure actual column widths
    col1_w = max(draw.textlength(line, font=font) for line in col1)
    col2_w = max(draw.textlength(line, font=font) for line in col2)
    total_w = col1_w + COL_GAP + col2_w
    x1 = int((W - total_w) // 2)
    x2 = int(x1 + col1_w + COL_GAP)

    y1 = (H - col1_h) // 2
    y2 = (H - col2_h) // 2
    for i, line in enumerate(col1):
        draw.text((x1, y1 + i * line_h), line, font=font, fill="black")
    for i, line in enumerate(col2):
        draw.text((x2, y2 + i * line_h), line, font=font, fill="black")
    layout = "2-column"
else:
    y = (H - total_h) // 2
    for i, line in enumerate(pairs):
        w_line = draw.textlength(line, font=font)
        x = int((W - w_line) // 2)
        draw.text((x, y + i * line_h), line, font=font, fill="black")
    layout = "1-column"

bg.save(str(OUT_PATH))
print(f"Saved {OUT_PATH}  ({len(pairs)} words, {layout})")
