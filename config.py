"""Central configuration for PetVoice.

Everything tunable lives here: Gemini model, thresholds, ranges, palette, text.
The API key is read from .env and never hardcoded.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = "PetVoice"
APP_TAGLINE = "Understand Their Habits. Care Beyond Words."
DB_PATH = BASE_DIR / "petfit.db"

# ---------------------------------------------------------------- Gemini
GEMINI_MODEL = "gemini-2.5-flash"   # change the model name here only
GEMINI_MAX_CALLS = 2                # hard cap per analysis run
GEMINI_TIMEOUT_SECONDS = 15
GEMINI_MAX_REPLY_CHARS = 1200       # longer replies are treated as failed


def get_gemini_api_key():
    """Return the API key from the environment, or None if missing/placeholder."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key.lower().startswith("your_"):
        return None
    return key


# -------------------------------------------------------------- Analysis
WINDOW_DAYS = 7              # latest 7 days vs previous 7 days
MIN_DAYS_FOR_ANALYSIS = 3    # fewer logged days in the latest window -> no analysis
MIN_DAYS_FOR_TREND = 3       # each window needs this many days to claim a trend
TREND_STABLE_PERCENT = 10    # changes within +/- this % are called "stable"

STATUS_LEVELS = ("normal", "watch", "consult_vet")

# General guidance only -- NOT veterinary standards. Broad and conservative.
# Food has no fixed range (it depends on size, diet and age), so the app
# compares food against the pet's own recent baseline instead.
SPECIES_RANGES = {
    "dog": {
        "activity_minutes": (30, 120),
        "sleep_hours": (10, 16),
        "water_ml_per_kg": (30, 90),
    },
    "cat": {
        "activity_minutes": (15, 90),
        "sleep_hours": (11, 18),
        "water_ml_per_kg": (30, 70),
    },
}

# ---------------------------------------------------------- Safety rules
FOOD_DROP_PERCENT = 50       # food this far below own average...
FOOD_DROP_DAYS = 2           # ...for this many days in a row
ZERO_WATER_DAYS = 2          # zero water logged for this many days in a row
SLEEP_HIGH_HOURS = 20        # a single day above this is flagged

# Words in owner notes that trigger a "consider mentioning to your vet" flag.
# This is keyword matching on what the owner wrote, not a diagnosis.
CONCERN_KEYWORDS = (
    "vomit", "vomiting", "blood", "limp", "limping", "lethargic", "lethargy",
    "not eating", "diarrhea", "diarrhoea", "collapse", "seizure",
    "straining", "difficulty breathing", "panting heavily",
)

# --------------------------------------------------- Input validation
MAX_ACTIVITY_MINUTES = 1440
MAX_FOOD_GRAMS = 5000
MAX_WATER_ML = 10000
MAX_SLEEP_HOURS = 24
MAX_WEIGHT_KG = 120
MAX_NOTES_CHARS = 2000

# ---------------------------------------------------------------- Theme
COLORS = {
    "navy": "#0B2545",
    "blue": "#2F6DB5",
    "teal": "#1FA6A0",
    "light_bg": "#F5F8FC",
    "card_bg": "#FFFFFF",
    "border": "#D9E2EC",
    "demo": "#B7791F",
}

# ------------------------------------------------------------------ Text
DEMO_LABEL = "Synthetic demo data"
GUIDANCE_LABEL = (
    "General guidance only. Ranges are broad, conservative reference values, "
    "not veterinary standards."
)
DISCLAIMER = (
    "PetVoice is an informational tool, not a medical device. It does not "
    "diagnose, treat or replace professional veterinary advice. If you are "
    "worried about your pet's health, contact a qualified veterinarian."
)