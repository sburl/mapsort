"""
Centralized, deterministic settings shared across pipeline scripts.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# Where the unzipped Google Takeout export lives. Override with
# TAKEOUT_DIR to point at a dated folder, e.g. "takeout-2026-02-27".
DATA_DIR = Path(os.environ.get("TAKEOUT_DIR") or BASE_DIR / "takeout")

# Takeout nests the saved-places file under the Google account it came
# from, so one export can hold several accounts. List yours here, or set
# GOOGLE_ACCOUNTS to a comma-separated list.
GOOGLE_ACCOUNTS = tuple(
    a.strip() for a in (os.environ.get("GOOGLE_ACCOUNTS") or "default").split(",") if a.strip()
)


def saved_places_json(account: str) -> Path:
    """Path to one account's Saved Places export inside DATA_DIR."""
    return DATA_DIR / account / "Maps (your places)" / "Saved Places.json"

RAW_JSON = OUTPUT_DIR / "places_raw.json"
RESOLVED_JSON = OUTPUT_DIR / "places_resolved.json"
FILTERED_JSON = OUTPUT_DIR / "places_filtered.json"
CLASSIFIED_JSON = OUTPUT_DIR / "places_classified.json"
REVIEW_CSV = OUTPUT_DIR / "places_review.csv"
LOW_CONFIDENCE_REVIEW_JSON = OUTPUT_DIR / "low_confidence_review.json"
RECLASSIFY_QUEUE_JSON = OUTPUT_DIR / "reclassification_queue.json"
RECLASSIFY_DECISION_TEMPLATE_CSV = OUTPUT_DIR / "reclassification_review_template.csv"
RECLASSIFICATION_REVIEW_UI_HTML = OUTPUT_DIR / "reclassification_review_ui.html"
MERGED_DATASET_JSON = OUTPUT_DIR / "places_merged.json"

LISTS_MD = BASE_DIR / "lists.md"
SCRAPED_DIR = OUTPUT_DIR / "scraped"
RAW_DIR = SCRAPED_DIR / "raw"
PLACES_SCRAPED = OUTPUT_DIR / "places_scraped.json"

# "all" reads every configured account; each account also gets its own
# preset so a single list can be re-imported on its own.
MAP_IMPORT_PRESETS = {
    "all": tuple((a, saved_places_json(a)) for a in GOOGLE_ACCOUNTS),
    **{a: ((a, saved_places_json(a)),) for a in GOOGLE_ACCOUNTS},
}

# Backward-compatible aliases for scripts that still use shorter names
CSV_PATH = REVIEW_CSV
REPORT_OUT = OUTPUT_DIR / "enrichment_report.csv"


# ---------------------------------------------------------------------------
# Classifier / enrichment / scraping controls
# ---------------------------------------------------------------------------

# sort.py
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
GEMINI_MODEL = "gemini-2.0-flash"
BATCH_SIZE = 50
HTTP_DELAY = 1.2       # seconds between HTTP fetches (phase 2)
HTTP_MAX_RETRIES = 3
CLASSIFICATION_MAX_RETRIES = 3
CLASSIFICATION_RETRY_DELAY_SECONDS = 2.0
KML_SPLIT_LIMIT = 450  # entries per KML file before splitting
ALLOWED_FETCH_DOMAINS = {"maps.google.com", "google.com", "www.google.com"}

# scrape.py
DEFAULT_DELAY = 4.0        # seconds between lists
PAGE_LOAD_WAIT = 5.0       # seconds to wait after DOM load for initial API call
PAGE_TIMEOUT = 60_000      # ms for navigation
ALLOWED_LIST_HOSTS = {"www.google.com", "google.com", "maps.google.com"}

# enrich.py
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
ALLOWED_GEOCODE_HOSTS = {"nominatim.openstreetmap.org"}
USER_AGENT = "MapsSort-enrichment/1.0 (personal project)"
DELAY = 1.1  # seconds between requests (Nominatim policy: max 1/sec)

# Optional backend service
BACKEND_BASE_URL = os.environ.get("MAPSORT_BACKEND_URL", "").strip()
BACKEND_REQUEST_TIMEOUT = 8.0
