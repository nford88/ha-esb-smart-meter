"""Constants for the ESB Smart Meter integration."""

from datetime import timedelta

DOMAIN = "esb_smart_meter"
PLATFORMS = ["sensor"]

# CSV import / processing
CONF_IMPORT_PATH = "import_path"
CONF_TIME_SHIFT_MINUTES = "time_shift_minutes"
CONF_CHEAP_START = "cheap_start"
CONF_CHEAP_END = "cheap_end"
CONF_NIGHT_START = "night_start"
CONF_DAY_START = "day_start"
CONF_PEAK_START = "peak_start"
CONF_PEAK_END = "peak_end"
CONF_RATES = "rates"
CONF_CURRENCY = "currency"
CONF_STANDING_CHARGE = "standing_charge"

# Optional ESB Networks portal download (opt-in)
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_MPRN = "mprn"

DEFAULT_IMPORT_PATH = "/config/esb_energy"
DEFAULT_TIME_SHIFT_MINUTES = -30
DEFAULT_CHEAP_START = "02:00"
DEFAULT_CHEAP_END = "04:00"
# Standard ESB smart-tariff band boundaries. Every supplier plan differs, so
# these are user-configurable; the ESB HDF export itself contains no tariff
# data, only consumption, so bands cannot be derived from the CSV.
DEFAULT_NIGHT_START = "23:00"
DEFAULT_DAY_START = "08:00"
DEFAULT_PEAK_START = "17:00"
DEFAULT_PEAK_END = "19:00"
DEFAULT_CURRENCY = "EUR"
DEFAULT_STANDING_CHARGE = 0.0
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)

# Rate buckets, in currency units per kWh.
DEFAULT_RATES = {
    "cheap": 0.08,
    "night": 0.1848,
    "day": 0.3451,
    "peak": 0.3617,
    "other": 0.3451,
}

# Ordered rate buckets the integration reports per period. "other" is retained
# for backwards compatibility and as a fallback rate but is no longer assigned
# by the (now contiguous) bucketing.
RATE_BUCKETS = ("cheap", "night", "day", "peak")

# Number of half-hour intervals in a complete day.
INTERVALS_PER_DAY = 48

# External-statistics identifiers used for the Energy dashboard backfill.
STAT_ENERGY_SUFFIX = "import_energy"
STAT_COST_SUFFIX = "import_cost"

SERVICE_RELOAD = "reload"
SERVICE_DOWNLOAD = "download_latest"
SERVICE_IMPORT_STATISTICS = "import_statistics"
SERVICE_PRUNE = "prune"

CONF_KEEP_DAYS = "keep_days"
DEFAULT_KEEP_DAYS = 90
