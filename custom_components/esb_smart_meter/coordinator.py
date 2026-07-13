"""Data coordinator for ESB Smart Meter."""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHEAP_END,
    CONF_CHEAP_START,
    CONF_CURRENCY,
    CONF_DAY_START,
    CONF_IMPORT_PATH,
    CONF_MPRN,
    CONF_NIGHT_START,
    CONF_PASSWORD,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_RATES,
    CONF_STANDING_CHARGE,
    CONF_TIME_SHIFT_MINUTES,
    CONF_USERNAME,
    DEFAULT_CHEAP_END,
    DEFAULT_CHEAP_START,
    DEFAULT_CURRENCY,
    DEFAULT_DAY_START,
    DEFAULT_IMPORT_PATH,
    DEFAULT_NIGHT_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_RATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_TIME_SHIFT_MINUTES,
    INTERVALS_PER_DAY,
    RATE_BUCKETS,
)

LOGGER = logging.getLogger(__name__)

DATETIME_COLUMNS = (
    "Read Date and End Time",
    "Read Date And End Time",
    "read_date_and_end_time",
    "datetime",
    "timestamp",
)
VALUE_COLUMNS = (
    "Read Value",
    "Read Value (kWh)",
    "read_value",
    "kWh",
    "kwh",
)


@dataclass(frozen=True)
class Reading:
    """One ESB half-hour reading (timezone-aware)."""

    when: datetime
    kwh: float
    source: str


class ESBSmartMeterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read ESB smart meter CSV exports and derive useful HA data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self._total_high_water = 0.0
        self._reload_settings()
        super().__init__(
            hass,
            LOGGER,
            name=entry.data.get(CONF_NAME, "ESB Smart Meter"),
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    def _conf(self, key: str, default: Any) -> Any:
        """Read a setting, preferring options over the original data."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    def _reload_settings(self) -> None:
        """(Re)load user settings from the config entry and its options."""
        self.import_path = Path(self._conf(CONF_IMPORT_PATH, DEFAULT_IMPORT_PATH))
        self.time_shift = int(
            self._conf(CONF_TIME_SHIFT_MINUTES, DEFAULT_TIME_SHIFT_MINUTES)
        )
        self.cheap_start = _parse_time(
            self._conf(CONF_CHEAP_START, DEFAULT_CHEAP_START), DEFAULT_CHEAP_START
        )
        self.cheap_end = _parse_time(
            self._conf(CONF_CHEAP_END, DEFAULT_CHEAP_END), DEFAULT_CHEAP_END
        )
        self.night_start = _parse_time(
            self._conf(CONF_NIGHT_START, DEFAULT_NIGHT_START), DEFAULT_NIGHT_START
        )
        self.day_start = _parse_time(
            self._conf(CONF_DAY_START, DEFAULT_DAY_START), DEFAULT_DAY_START
        )
        self.peak_start = _parse_time(
            self._conf(CONF_PEAK_START, DEFAULT_PEAK_START), DEFAULT_PEAK_START
        )
        self.peak_end = _parse_time(
            self._conf(CONF_PEAK_END, DEFAULT_PEAK_END), DEFAULT_PEAK_END
        )
        self.rates = DEFAULT_RATES | dict(self._conf(CONF_RATES, {}))
        self.currency = self._conf(CONF_CURRENCY, DEFAULT_CURRENCY)
        self.standing_charge = float(
            self._conf(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE)
        )

    def has_download_credentials(self) -> bool:
        """Return True if ESB portal download is configured."""
        return bool(
            self.entry.data.get(CONF_USERNAME)
            and self.entry.data.get(CONF_PASSWORD)
            and self.entry.data.get(CONF_MPRN)
        )

    async def async_download_latest(self) -> None:
        """Download the latest ESB CSV, then refresh sensors.

        This is intentionally only wired to an explicit service call: ESB
        rate-limits logins heavily (roughly a couple of attempts per day), so
        it must not run on the regular polling interval.
        """
        await self.hass.async_add_executor_job(self._download_latest)
        await self.async_request_refresh()

    def _download_latest(self) -> None:
        """Download the latest ESB CSV into the import folder (executor)."""
        # Imported lazily so the optional beautifulsoup4/requests dependency is
        # only touched when the user actually uses the portal download.
        from .downloader import ESBDownloadError, download_latest_csv

        username = self.entry.data.get(CONF_USERNAME)
        password = self.entry.data.get(CONF_PASSWORD)
        mprn = self.entry.data.get(CONF_MPRN)
        if not username or not password or not mprn:
            raise ESBDownloadError(
                "ESB username, password, and MPRN must be configured to download."
            )

        self.import_path.mkdir(parents=True, exist_ok=True)
        result = download_latest_csv(username=username, password=password, mprn=mprn)
        output_path = self.import_path / "esb_latest.csv"
        output_path.write_text(result.csv_text, encoding="utf-8")
        LOGGER.info(
            "Downloaded ESB CSV to %s (%s rows, source filename: %s)",
            output_path,
            result.rows,
            result.filename,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and process CSV data."""
        return await self.hass.async_add_executor_job(self._read_data)

    def _read_data(self) -> dict[str, Any]:
        """Read CSV data from disk and derive period totals."""
        self.import_path.mkdir(parents=True, exist_ok=True)
        readings = self._load_readings()
        now = dt_util.now()

        if not readings:
            current_bucket = self._bucket_for(now)
            return {
                "available": False,
                "records": 0,
                "files": [],
                "last_import": now,
                "current_bucket": current_bucket,
                "current_rate": self._rate(current_bucket),
                "message": f"No ESB CSV rows found in {self.import_path}",
            }

        readings.sort(key=lambda item: item.when)
        latest = readings[-1]
        today = now.date()
        yesterday = today - timedelta(days=1)
        month_start = today.replace(day=1)

        periods: dict[date, dict[str, float]] = {}
        reading_counts: dict[date, int] = defaultdict(int)
        total_kwh = 0.0

        for reading in readings:
            bucket = self._bucket_for(reading.when)
            cost = reading.kwh * self._rate(bucket)
            total_kwh += reading.kwh

            reading_date = reading.when.date()
            reading_counts[reading_date] += 1
            period = periods.setdefault(reading_date, _empty_one_period())
            _add_bucket(period, bucket, reading.kwh, cost)

        today_period = self._finalize_period(periods.get(today), days=1)
        yesterday_period = self._finalize_period(periods.get(yesterday), days=1)

        month_days = [d for d in periods if month_start <= d <= today]
        month_raw = _empty_one_period()
        for day in month_days:
            _merge_period(month_raw, periods[day])
        month_period = self._finalize_period(month_raw, days=len(month_days))

        complete_dates = sorted(
            day for day, count in reading_counts.items() if count >= INTERVALS_PER_DAY
        )
        last_7 = [
            _period_summary(day, self._finalize_period(periods[day], days=1))
            for day in complete_dates[-7:]
        ]
        last_7_cost = round(sum(item["cost"] for item in last_7), 3)
        last_7_kwh = round(sum(item["total_kwh"] for item in last_7), 3)

        month_complete_days = [d for d in complete_dates if month_start <= d <= today]
        days_in_month = _days_in_month(today)
        projected_month_cost = (
            round(month_period["cost"] / len(month_complete_days) * days_in_month, 2)
            if month_complete_days
            else 0.0
        )

        total_kwh = round(total_kwh, 3)
        if total_kwh < self._total_high_water:
            LOGGER.debug(
                "Computed total import %.3f kWh is below previous high-water "
                "mark %.3f kWh (CSV removed?); holding the higher value",
                total_kwh,
                self._total_high_water,
            )
            total_kwh = self._total_high_water
        else:
            self._total_high_water = total_kwh

        coverage_days = (latest.when.date() - readings[0].when.date()).days + 1
        current_bucket = self._bucket_for(now)

        return {
            "available": True,
            "records": len(readings),
            "files": sorted({reading.source for reading in readings}),
            "last_import": now,
            "first_reading": readings[0].when,
            "last_reading": latest.when,
            "last_interval_kwh": latest.kwh,
            "last_reading_age_hours": round(
                (now - latest.when).total_seconds() / 3600, 1
            ),
            "coverage_days": coverage_days,
            "total_import_kwh": total_kwh,
            "current_bucket": current_bucket,
            "current_rate": self._rate(current_bucket),
            "currency": self.currency,
            "today": today_period,
            "yesterday": yesterday_period,
            "month": month_period,
            "last_7_complete_days": last_7,
            "last_7_cost": last_7_cost,
            "last_7_energy": last_7_kwh,
            "last_7_average_daily_cost": round(last_7_cost / len(last_7), 3)
            if last_7
            else 0.0,
            "month_complete_day_count": len(month_complete_days),
            "projected_month_cost": projected_month_cost,
            "message": "OK",
        }

    def costed_readings(self) -> list[tuple[datetime, float, float]]:
        """Return (when, kwh, cost) for every reading, sorted by time.

        Used by the statistics backfill. Runs the same parsing as a refresh.
        """
        readings = self._load_readings()
        readings.sort(key=lambda item: item.when)
        return [
            (r.when, r.kwh, r.kwh * self._rate(self._bucket_for(r.when)))
            for r in readings
        ]

    def _rate(self, bucket: str) -> float:
        """Return the configured rate for a bucket, falling back to 'other'."""
        return self.rates.get(bucket, self.rates.get("other", 0.0))

    def _finalize_period(
        self, period: dict[str, float] | None, *, days: int
    ) -> dict[str, float]:
        """Round a period and fold in the daily standing charge."""
        period = period or _empty_one_period()
        standing = self.standing_charge * days
        result: dict[str, float] = {
            "total_kwh": round(period.get("total_kwh", 0.0), 3),
            "energy_cost": round(period.get("cost", 0.0), 3),
            "standing_charge": round(standing, 3),
            "cost": round(period.get("cost", 0.0) + standing, 3),
        }
        for bucket in RATE_BUCKETS:
            result[f"{bucket}_kwh"] = round(period.get(f"{bucket}_kwh", 0.0), 3)
            result[f"{bucket}_cost"] = round(period.get(f"{bucket}_cost", 0.0), 3)
        return result

    def _load_readings(self) -> list[Reading]:
        """Load valid readings from all CSV files in the import folder."""
        by_timestamp: dict[datetime, Reading] = {}
        for csv_path in sorted(self.import_path.glob("*.csv")):
            for reading in self._read_csv(csv_path):
                by_timestamp[reading.when] = reading
        return list(by_timestamp.values())

    def _read_csv(self, csv_path: Path) -> list[Reading]:
        """Read a single CSV file if it looks like an ESB interval file."""
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
                sample = file_obj.read(4096)
                file_obj.seek(0)
                dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
                reader = csv.DictReader(file_obj, dialect=dialect)
                if not reader.fieldnames:
                    return []
                datetime_col = _find_column(reader.fieldnames, DATETIME_COLUMNS)
                value_col = _find_column(reader.fieldnames, VALUE_COLUMNS)
                if datetime_col is None or value_col is None:
                    return []

                readings: list[Reading] = []
                for row in reader:
                    when = _parse_datetime(row.get(datetime_col, ""))
                    kwh = _parse_float(row.get(value_col, ""))
                    if when is None or kwh is None:
                        continue
                    if self.time_shift:
                        when += timedelta(minutes=self.time_shift)
                    readings.append(
                        Reading(when=_as_local(when), kwh=kwh, source=csv_path.name)
                    )
                return readings
        except Exception as err:  # noqa: BLE001 - keep one bad CSV from killing HA setup
            LOGGER.warning("Unable to parse ESB CSV %s: %s", csv_path, err)
            return []

    def _bucket_for(self, value: datetime | time) -> str:
        """Return the configured rate bucket for a local time.

        All band boundaries are user-configurable because they depend on the
        end user's supplier plan (the ESB CSV contains no tariff data). With the
        default smart-tariff boundaries the bands are contiguous, so every
        half-hour maps to exactly one bucket and cheap + night + day + peak sum
        to the total:

            cheap  configurable boost window (default 02:00-04:00), highest priority
            peak   peak_start-peak_end (default 17:00-19:00)
            night  night_start wrapping to day_start (default 23:00-08:00)
            day    everything else (default 08:00-17:00 and 19:00-23:00)
        """
        local = value.time() if isinstance(value, datetime) else value
        if _time_in_range(local, self.cheap_start, self.cheap_end):
            return "cheap"
        if _time_in_range(local, self.peak_start, self.peak_end):
            return "peak"
        if _time_in_range(local, self.night_start, self.day_start):
            return "night"
        return "day"


def _empty_one_period() -> dict[str, float]:
    """Return empty totals for one period."""
    return defaultdict(float, {"total_kwh": 0.0, "cost": 0.0})


def _add_bucket(target: dict[str, float], bucket: str, kwh: float, cost: float) -> None:
    """Add kWh and cost to a period bucket."""
    target[f"{bucket}_kwh"] += kwh
    target[f"{bucket}_cost"] += cost
    target["total_kwh"] += kwh
    target["cost"] += cost


def _merge_period(target: dict[str, float], other: dict[str, float]) -> None:
    """Accumulate one period's raw totals into another."""
    for key, value in other.items():
        target[key] += value


def _period_summary(day: date, period: dict[str, float]) -> dict[str, Any]:
    """Return a rounded daily summary for the last-7-days attribute."""
    summary: dict[str, Any] = {
        "date": day.isoformat(),
        "total_kwh": period["total_kwh"],
        "cost": period["cost"],
    }
    for bucket in RATE_BUCKETS:
        summary[f"{bucket}_kwh"] = period[f"{bucket}_kwh"]
        summary[f"{bucket}_cost"] = period[f"{bucket}_cost"]
    return summary


def _days_in_month(value: date) -> int:
    """Return number of days in the date's month."""
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return (next_month - date(value.year, value.month, 1)).days


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    """Find a CSV column by exact or normalized name."""
    normalized = {_normalize(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
        match = normalized.get(_normalize(candidate))
        if match:
            return match
    for fieldname in fieldnames:
        lower = fieldname.lower()
        if "read" in lower and "date" in lower and "time" in lower:
            return fieldname
    return None


def _normalize(value: str) -> str:
    """Normalize a column name."""
    return value.lower().replace(" ", "").replace("_", "").replace("-", "")


def _parse_datetime(raw: str) -> datetime | None:
    """Parse common ESB timestamp formats (returns naive local wall time)."""
    value = raw.strip()
    if not value:
        return None
    for fmt in (
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_local(value: datetime) -> datetime:
    """Attach HA's local timezone to a naive wall-clock datetime (DST-aware)."""
    if value.tzinfo is not None:
        return value
    tzinfo = dt_util.DEFAULT_TIME_ZONE or dt_util.UTC
    return value.replace(tzinfo=tzinfo)


def _parse_float(raw: str | None) -> float | None:
    """Parse a float value."""
    if raw is None:
        return None
    value = raw.strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_time(raw: str, fallback: str) -> time:
    """Parse HH:MM time."""
    for value in (raw, fallback):
        try:
            hour, minute = value.split(":", 1)
            return time(int(hour), int(minute))
        except (TypeError, ValueError, AttributeError):
            continue
    return time(0, 0)


def _time_in_range(value: time, start: time, end: time) -> bool:
    """Check if a time is inside a range, including ranges crossing midnight."""
    if start <= end:
        return start <= value < end
    return value >= start or value < end
