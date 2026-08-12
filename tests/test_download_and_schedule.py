"""Tests for download-status tracking and the automatic download scheduler."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter import scheduler as sched
from custom_components.esb_smart_meter.const import (
    CONF_DOWNLOAD_MODE,
    CONF_IMPORT_PATH,
    CONF_INTERVAL_MINUTES,
    CONF_MPRN,
    CONF_PASSWORD,
    CONF_TIME_SHIFT_MINUTES,
    CONF_USERNAME,
    CONF_WINDOW_START_HOUR,
    DOMAIN,
    DOWNLOAD_MODE_DAILY_WINDOW,
    DOWNLOAD_MODE_INTERVAL,
    DOWNLOAD_MODE_MANUAL,
    DOWNLOAD_STATUS_CAPTCHA,
    DOWNLOAD_STATUS_FAILED,
    DOWNLOAD_STATUS_OK,
    MIN_INTERVAL_MINUTES,
)
from custom_components.esb_smart_meter.coordinator import ESBSmartMeterCoordinator
from custom_components.esb_smart_meter.downloader import (
    ESBCaptchaError,
    ESBDownloadError,
)


def _entry(path, **data):
    payload = {CONF_IMPORT_PATH: str(path), CONF_TIME_SHIFT_MINUTES: 0}
    payload.update(data)
    return MockConfigEntry(domain=DOMAIN, data=payload)


def _creds_entry(path, **data):
    return _entry(
        path,
        **{
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "pw",
            CONF_MPRN: "10300000000",
            **data,
        },
    )


# --- download status ------------------------------------------------------


async def test_status_recorded_on_success(hass, csv_dir, monkeypatch):
    coordinator = ESBSmartMeterCoordinator(hass, _creds_entry(csv_dir))
    monkeypatch.setattr(coordinator, "_download_latest", lambda: 42)

    ok = await coordinator.async_download_latest(raise_on_error=False)

    assert ok is True
    assert coordinator.last_download_status == DOWNLOAD_STATUS_OK
    assert coordinator.last_download_rows == 42
    assert coordinator.last_download_error is None
    assert coordinator.data["download_status"] == DOWNLOAD_STATUS_OK


async def test_status_recorded_on_failure(hass, csv_dir, monkeypatch):
    coordinator = ESBSmartMeterCoordinator(hass, _creds_entry(csv_dir))

    def _boom():
        raise ESBDownloadError("no auth form")

    monkeypatch.setattr(coordinator, "_download_latest", _boom)

    ok = await coordinator.async_download_latest(raise_on_error=False)

    assert ok is False
    assert coordinator.last_download_status == DOWNLOAD_STATUS_FAILED
    assert coordinator.last_download_error == "no auth form"
    assert coordinator.data["download_status"] == DOWNLOAD_STATUS_FAILED
    assert coordinator.data["download_error"] == "no auth form"


async def test_status_recorded_on_captcha(hass, csv_dir, monkeypatch):
    coordinator = ESBSmartMeterCoordinator(hass, _creds_entry(csv_dir))

    def _captcha():
        raise ESBCaptchaError("blocked by captcha")

    monkeypatch.setattr(coordinator, "_download_latest", _captcha)

    ok = await coordinator.async_download_latest(raise_on_error=False)

    assert ok is False
    assert coordinator.last_download_status == DOWNLOAD_STATUS_CAPTCHA


async def test_manual_service_reraises(hass, csv_dir, monkeypatch):
    coordinator = ESBSmartMeterCoordinator(hass, _creds_entry(csv_dir))

    def _boom():
        raise ESBDownloadError("boom")

    monkeypatch.setattr(coordinator, "_download_latest", _boom)

    with pytest.raises(ESBDownloadError):
        await coordinator.async_download_latest(raise_on_error=True)
    # ...but the status is still recorded for the UI
    assert coordinator.last_download_status == DOWNLOAD_STATUS_FAILED


# --- scheduler ------------------------------------------------------------


@pytest.fixture
def sched_calls(monkeypatch):
    """Patch the scheduler's timers and record how they were registered."""
    calls = {"time_change": [], "call_later": []}

    def _fake_time_change(hass, action, *, hour=None, minute=None, second=None):
        calls["time_change"].append({"hour": hour, "minute": minute, "second": second})
        return lambda: None

    def _fake_call_later(hass, delay, action):
        calls["call_later"].append({"delay": delay})
        return lambda: None

    monkeypatch.setattr(sched, "async_track_time_change", _fake_time_change)
    monkeypatch.setattr(sched, "async_call_later", _fake_call_later)
    return calls


def _seeded_coordinator(hass, entry):
    """A coordinator with data already 'available' so the scheduler's one-time
    initial download does not fire and muddy the timer counts."""
    coordinator = ESBSmartMeterCoordinator(hass, entry)
    coordinator.data = {"available": True}
    return coordinator


async def test_manual_mode_schedules_nothing(hass, csv_dir, sched_calls):
    entry = _creds_entry(csv_dir, **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_MANUAL})
    coordinator = _seeded_coordinator(hass, entry)
    sched.async_setup_download_schedule(hass, entry, coordinator)
    assert sched_calls["time_change"] == []
    assert sched_calls["call_later"] == []


async def test_no_credentials_schedules_nothing(hass, csv_dir, sched_calls):
    entry = _entry(csv_dir, **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_DAILY_WINDOW})
    coordinator = _seeded_coordinator(hass, entry)
    sched.async_setup_download_schedule(hass, entry, coordinator)
    assert sched_calls["time_change"] == []
    assert sched_calls["call_later"] == []


async def test_daily_window_registers_time_change(hass, csv_dir, sched_calls):
    entry = _creds_entry(
        csv_dir,
        **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_DAILY_WINDOW, CONF_WINDOW_START_HOUR: 10},
    )
    coordinator = _seeded_coordinator(hass, entry)
    sched.async_setup_download_schedule(hass, entry, coordinator)
    assert len(sched_calls["time_change"]) == 1
    assert sched_calls["time_change"][0]["hour"] == 10
    assert coordinator.next_download_time is not None


async def test_interval_mode_schedules_call_later_with_jitter(
    hass, csv_dir, sched_calls
):
    entry = _creds_entry(
        csv_dir,
        **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_INTERVAL, CONF_INTERVAL_MINUTES: 120},
    )
    coordinator = _seeded_coordinator(hass, entry)
    sched.async_setup_download_schedule(hass, entry, coordinator)
    assert sched_calls["time_change"] == []
    assert len(sched_calls["call_later"]) == 1
    delay = sched_calls["call_later"][0]["delay"]
    assert 120 * 60 * 0.9 <= delay <= 120 * 60 * 1.1


async def test_interval_mode_clamps_below_floor(hass, csv_dir, sched_calls):
    entry = _creds_entry(
        csv_dir,
        **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_INTERVAL, CONF_INTERVAL_MINUTES: 5},
    )
    coordinator = _seeded_coordinator(hass, entry)
    sched.async_setup_download_schedule(hass, entry, coordinator)
    delay = sched_calls["call_later"][0]["delay"]
    floor = MIN_INTERVAL_MINUTES * 60
    assert floor * 0.9 <= delay <= floor * 1.1


async def test_initial_download_scheduled_when_no_data(hass, csv_dir, sched_calls):
    entry = _creds_entry(
        csv_dir,
        **{CONF_DOWNLOAD_MODE: DOWNLOAD_MODE_DAILY_WINDOW, CONF_WINDOW_START_HOUR: 10},
    )
    coordinator = ESBSmartMeterCoordinator(hass, entry)
    coordinator.data = None  # nothing downloaded yet
    sched.async_setup_download_schedule(hass, entry, coordinator)
    # daily window schedule + a one-shot initial download soon after setup
    assert len(sched_calls["time_change"]) == 1
    assert any(c["delay"] == 10 for c in sched_calls["call_later"])
