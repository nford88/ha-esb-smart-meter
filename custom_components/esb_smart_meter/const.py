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
CONF_EXPORT_RATE = "export_rate"
CONF_VAT_PERCENT = "vat_percent"
CONF_DISCOUNT_PERCENT = "discount_percent"

# Optional ESB Networks portal download (opt-in)
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_MPRN = "mprn"

# Automatic portal-download schedule. Every download is a fresh login against
# ESB's bot-detecting Azure B2C flow, so the schedule is the entire exposure:
# - manual (default): never auto-download; user calls the download service
# - daily_window: one download per day at a random time inside a window
# - interval: a download every N minutes after the previous one
CONF_DOWNLOAD_MODE = "download_mode"
DOWNLOAD_MODE_MANUAL = "manual"
DOWNLOAD_MODE_DAILY_WINDOW = "daily_window"
DOWNLOAD_MODE_INTERVAL = "interval"
DEFAULT_DOWNLOAD_MODE = DOWNLOAD_MODE_MANUAL

CONF_WINDOW_START_HOUR = "download_window_start_hour"
CONF_WINDOW_END_HOUR = "download_window_end_hour"
DEFAULT_WINDOW_START_HOUR = 9
DEFAULT_WINDOW_END_HOUR = 12

CONF_INTERVAL_MINUTES = "download_interval_minutes"
DEFAULT_INTERVAL_MINUTES = 24 * 60
# Anything more frequent risks ESB's multi-hour captcha lockout.
MIN_INTERVAL_MINUTES = 30

# After a failed scheduled download, retry once this many hours later (captcha
# lockouts clear in ~6h), then wait for the next slot.
RETRY_MIN_HOURS = 6
RETRY_MAX_HOURS = 8

# download_latest status, surfaced through a sensor so the UI can show whether
# the last automatic download succeeded and, if not, why.
DOWNLOAD_STATUS_OK = "ok"
DOWNLOAD_STATUS_FAILED = "failed"
DOWNLOAD_STATUS_CAPTCHA = "captcha_lockout"
DOWNLOAD_STATUS_NEVER = "never_run"

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

# The configured unit rates and standing charge are treated as NET (ex-VAT)
# amounts. A bill is then built the way a supplier builds one:
#
#     subtotal  = energy + standing charge      (both net)
#     discount  = subtotal * discount_percent
#     net       = subtotal - discount
#     VAT       = net * vat_percent
#     total     = net + VAT
#
# The discount comes off before VAT because VAT is charged on the amount
# actually payable, not on the pre-discount figure.
#
# 9% is the Irish VAT rate on domestic electricity. It applies to the standing
# charge as well as to units.
DEFAULT_VAT_PERCENT = 9.0
# Supplier welcome/loyalty/direct-debit discounts vary by plan, so this starts
# at zero and is the user's to set.
DEFAULT_DISCOUNT_PERCENT = 0.0
# Feed-in tariff / microgeneration export payment, in currency units per kWh.
DEFAULT_EXPORT_RATE = 0.0
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

# ESB HDF "Read Type" column: rows are tagged import or export. A single export
# contains both when the meter has microgeneration.
READTYPE_COLUMNS = ("Read Type", "read_type", "read type")
EXPORT_KEYWORD = "export"

# ESB HDF "Read Value" is a MEAN POWER in kW sustained over each half-hour
# interval, not an energy figure - the column header says so: "Active Import
# Interval (kW)". Energy is therefore value * 0.5 h. Without this factor every
# reading is double-counted; verified against an independent inverter CT meter,
# where the scaled figures agree to within ~4% and the unscaled ones are ~2.0x.
INTERVAL_HOURS = 0.5

# Column headers that already publish energy rather than mean power. If a future
# ESB export uses one of these, the interval scaling must not be applied.
ENERGY_HEADER_MARKER = "kwh"

# External-statistics identifiers used for the Energy dashboard backfill.
STAT_ENERGY_SUFFIX = "import_energy"
STAT_COST_SUFFIX = "import_cost"
# Microgeneration counterparts, so exported energy and feed-in earnings get the
# same backdated history on the Energy dashboard as consumption does.
STAT_EXPORT_ENERGY_SUFFIX = "export_energy"
STAT_EXPORT_EARNINGS_SUFFIX = "export_earnings"

SERVICE_RELOAD = "reload"
SERVICE_DOWNLOAD = "download_latest"
SERVICE_IMPORT_STATISTICS = "import_statistics"
SERVICE_PRUNE = "prune"

CONF_KEEP_DAYS = "keep_days"
DEFAULT_KEEP_DAYS = 90

# import_statistics: rewrite the whole series from a zero baseline instead of
# resuming from the newest point already in the recorder.
CONF_REBUILD = "rebuild"
