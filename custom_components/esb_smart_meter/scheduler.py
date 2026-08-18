"""Automatic ESB portal-download scheduling.

Every download is a fresh login against ESB's bot-detecting Azure B2C flow, so
the schedule is the integration's entire bot-detection exposure. Two modes:

- daily_window: one download per day at a random time inside a window, with the
  time re-randomised each day (a download at the same instant every day is
  itself a bot signature). One retry a few hours after a failure.
- interval: a download every N minutes after the previous one finishes, with
  +/-10% jitter so repeated logins never form an exact clockwork period.

Sensors read from disk on their own 30-minute cadence and never trigger a login;
only this scheduler does.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DOWNLOAD_MODE,
    CONF_INTERVAL_MINUTES,
    CONF_WINDOW_END_HOUR,
    CONF_WINDOW_START_HOUR,
    DEFAULT_DOWNLOAD_MODE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_WINDOW_END_HOUR,
    DEFAULT_WINDOW_START_HOUR,
    DOWNLOAD_MODE_INTERVAL,
    DOWNLOAD_MODE_MANUAL,
    MIN_INTERVAL_MINUTES,
    RETRY_MAX_HOURS,
    RETRY_MIN_HOURS,
)
from .coordinator import ESBSmartMeterCoordinator

LOGGER = logging.getLogger(__name__)


def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return the effective option value (options over data)."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def async_setup_download_schedule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ESBSmartMeterCoordinator,
) -> Callable[[], None]:
    """Start the configured download schedule; return an unsubscribe callable."""
    mode = _opt(entry, CONF_DOWNLOAD_MODE, DEFAULT_DOWNLOAD_MODE)
    if mode == DOWNLOAD_MODE_MANUAL or not coordinator.has_download_credentials():
        return lambda: None
    if mode == DOWNLOAD_MODE_INTERVAL:
        return _setup_interval(hass, entry, coordinator)
    return _setup_daily_window(hass, entry, coordinator)


def _setup_daily_window(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ESBSmartMeterCoordinator,
) -> Callable[[], None]:
    """One download per day at a random time inside [start, end)."""
    start = int(_opt(entry, CONF_WINDOW_START_HOUR, DEFAULT_WINDOW_START_HOUR))
    end = int(_opt(entry, CONF_WINDOW_END_HOUR, DEFAULT_WINDOW_END_HOUR))
    if not 0 <= start < end <= 24:
        LOGGER.warning(
            "ESB %s: invalid download window %s-%s; using default %02d:00-%02d:00",
            coordinator.name,
            start,
            end,
            DEFAULT_WINDOW_START_HOUR,
            DEFAULT_WINDOW_END_HOUR,
        )
        start, end = DEFAULT_WINDOW_START_HOUR, DEFAULT_WINDOW_END_HOUR
    window_seconds = (end - start) * 3600
    # Cancel handles for the pending jittered-download and retry timers.
    handles: dict[str, Callable[[], None] | None] = {"download": None, "retry": None}

    async def _retry(_now: Any = None) -> None:
        await coordinator.async_download_latest(raise_on_error=False)

    async def _download(_now: Any = None) -> None:
        if await coordinator.async_download_latest(raise_on_error=False):
            return
        retry = random.randint(RETRY_MIN_HOURS * 3600, RETRY_MAX_HOURS * 3600)
        LOGGER.info(
            "ESB %s: download failed; retrying once in %.1fh",
            coordinator.name,
            retry / 3600,
        )
        handles["retry"] = async_call_later(hass, retry, _retry)

    @callback
    def _fire(now: Any) -> None:
        # Random offset inside the window, re-picked each day. Scheduled via
        # async_call_later — a proper HA timer that is tracked and cancelled on
        # unload. The previous approach (a background task doing a multi-hour
        # asyncio.sleep) was garbage-collected mid-sleep by HA, so the download
        # never ran ("Task was destroyed but it is pending").
        jitter = random.randint(0, max(0, window_seconds - 1))
        coordinator.next_download_time = dt_util.now() + timedelta(seconds=jitter)
        LOGGER.info(
            "ESB %s: daily download window open; downloading in %dh%02dm",
            coordinator.name,
            jitter // 3600,
            (jitter % 3600) // 60,
        )
        handles["download"] = async_call_later(hass, jitter, _download)

    coordinator.next_download_time = _next_daily(start)
    _maybe_initial_download(hass, entry, coordinator)
    unsub_time = async_track_time_change(hass, _fire, hour=start, minute=0, second=0)

    def _cancel() -> None:
        unsub_time()
        for handle in handles.values():
            if handle is not None:
                handle()

    return _cancel


def _setup_interval(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ESBSmartMeterCoordinator,
) -> Callable[[], None]:
    """A download every N minutes after the previous one, with +/-10% jitter."""
    minutes = int(_opt(entry, CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES))
    if minutes < MIN_INTERVAL_MINUTES:
        LOGGER.warning(
            "ESB %s: download interval %s min below the %d min floor; clamping",
            coordinator.name,
            minutes,
            MIN_INTERVAL_MINUTES,
        )
        minutes = MIN_INTERVAL_MINUTES
    interval_seconds = minutes * 60
    handle: dict[str, Callable[[], None] | None] = {"cancel": None}

    async def _run(_now: Any = None) -> None:
        await coordinator.async_download_latest(raise_on_error=False)
        _schedule()

    def _schedule() -> None:
        jitter = max(60, interval_seconds // 10)
        delay = interval_seconds + random.randint(-jitter, jitter)
        coordinator.next_download_time = dt_util.now() + timedelta(seconds=delay)
        LOGGER.info("ESB %s: next download in %.1fh", coordinator.name, delay / 3600)
        handle["cancel"] = async_call_later(hass, delay, _run)

    _schedule()
    _maybe_initial_download(hass, entry, coordinator)

    def _unsub() -> None:
        if handle["cancel"] is not None:
            handle["cancel"]()

    return _unsub


def _maybe_initial_download(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ESBSmartMeterCoordinator,
) -> None:
    """Kick off one download shortly after setup if there is no data yet.

    Only when the folder has no readings, so ordinary restarts (which already
    have CSVs on disk) never trigger an extra login.
    """
    if coordinator.data and coordinator.data.get("available"):
        return

    async def _initial(_now: Any = None) -> None:
        await coordinator.async_download_latest(raise_on_error=False)

    async_call_later(hass, 10, _initial)


def _next_daily(hour: int):
    """Return the next occurrence of ``hour``:00 local time, for display."""
    now = dt_util.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target
