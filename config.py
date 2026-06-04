"""Central configuration. Values come from environment variables (.env locally,
or the runner environment in GitHub Actions). dotenv is optional so the
collector can run on Actions with only `requests` installed."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Location (defaults to Edinburgh city centre) ---
LATITUDE = float(os.getenv("LATITUDE", "55.9533"))
LONGITUDE = float(os.getenv("LONGITUDE", "-3.1883"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")

_BASE = os.path.dirname(__file__)

# Symptoms live in SQLite on the always-on machine (the Mac). Not committed.
DB_PATH = os.getenv("DB_PATH", os.path.join(_BASE, "allergy.db"))

# Pollen lives in a CSV committed to the repo. Actions writes it; the bot reads it.
POLLEN_CSV = os.getenv("POLLEN_CSV", os.path.join(_BASE, "data", "pollen.csv"))

# On the Mac, set POLLEN_CSV_URL to the raw GitHub URL of data/pollen.csv, e.g.
#   https://raw.githubusercontent.com/<you>/<repo>/main/data/pollen.csv
# so the bot always reads what Actions last committed, with no git pull needed.
POLLEN_CSV_URL = os.getenv("POLLEN_CSV_URL") or None

# Where readers (bot, analysis) pull pollen from: the URL if set, else local file.
POLLEN_SOURCE = POLLEN_CSV_URL or POLLEN_CSV

# --- Telegram (only needed on the Mac, never in Actions) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID") or None

# --- Open-Meteo Air Quality API (CAMS European pollen, ~11 km, no key) ---
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN_SPECIES = [
    "alder_pollen",
    "birch_pollen",
    "grass_pollen",
    "mugwort_pollen",
    "olive_pollen",
    "ragweed_pollen",
]
