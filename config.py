import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# API keys
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DEEPL_API_KEY = os.environ["DEEPL_API_KEY"]
MONGODB_URI = os.getenv("MONGODB_URI")  # optional until Atlas is configured

# Video
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
IMAGEMAGICK_BINARY = "/opt/homebrew/bin/convert"

# TTS provider: "openai" or "gtts"
DEFAULT_TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai")

# Paths
OUTPUT_DIR = Path("output")
BACKGROUND_IMAGE = Path("input/assets/background.png")
