"""Tests for the ESB Smart Meter coordinator."""

from datetime import time

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_IMPORT_PATH,
    CONF_RATES,
    CONF_STANDING_CHARGE,
    CONF_TIME_SHIFT_MINUTES,
    DOMAIN,
)
from custom_components.esb_smart_meter.coordinator import ESBSmartMeterCoordinator


def _entry(path, **data):
    payload = {CONF_IMPORT_PATH: str(path), CONF_TIME_SHIFT_MINUTES: 0}
    payload.update(data)
    return MockConfigEntry(domain=DOMAIN, data=payload)


async def test_reads_and_totals(hass, csv_dir):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(csv_dir))
    data = await coordinator._async_update_data()
    assert data["available"] is True
    assert data["records"] == 5
    assert data["total_import_kwh"] == pytest.approx(3.2)
    assert data["files"] == ["esb.csv"]


async def test_no_data(hass, tmp_path):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["available"] is False
    assert data["records"] == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (time(3, 0), "cheap"),
        (time(2, 0), "cheap"),
        (time(4, 0), "night"),  # end exclusive
        (time(18, 0), "peak"),
        (time(18, 30), "peak"),
        (time(12, 0), "day"),
        (time(22, 30), "day"),
        (time(7, 30), "night"),
        (time(23, 0), "night"),
    ],
)
async def test_bucket_boundaries(hass, tmp_path, value, expected):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    assert coordinator._bucket_for(value) == expected


async def test_buckets_partition_the_day(hass, tmp_path):
    """cheap + night + day + peak must cover all 48 half-hours exactly once."""
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    seen = set()
    for hour in range(24):
        for minute in (0, 30):
            bucket = coordinator._bucket_for(time(hour, minute))
            assert bucket in {"cheap", "night", "day", "peak"}
            seen.add(bucket)
    assert seen == {"cheap", "night", "day", "peak"}


async def test_today_costs_and_standing_charge(hass, tmp_path):
    day = dt_util.now().strftime("%d-%m-%Y")
    (tmp_path / "today.csv").write_text(
        "Read Date and End Time,Read Value\n" f"{day} 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(tmp_path, **{CONF_STANDING_CHARGE: 0.5, CONF_RATES: {"day": 0.30}}),
    )
    data = await coordinator._async_update_data()
    today = data["today"]
    assert today["total_kwh"] == pytest.approx(2.0)
    assert today["day_kwh"] == pytest.approx(2.0)
    assert today["energy_cost"] == pytest.approx(0.6)
    assert today["standing_charge"] == pytest.approx(0.5)
    assert today["cost"] == pytest.approx(1.1)


async def test_total_never_drops(hass, tmp_path):
    csv_path = tmp_path / "h.csv"
    csv_path.write_text(
        "Read Date and End Time,Read Value\n01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    first = await coordinator._async_update_data()
    assert first["total_import_kwh"] == pytest.approx(2.0)

    # Rewrite with a smaller value: the high-water mark should hold the total.
    csv_path.write_text(
        "Read Date and End Time,Read Value\n01-01-2026 12:00,1.000\n",
        encoding="utf-8",
    )
    second = await coordinator._async_update_data()
    assert second["total_import_kwh"] == pytest.approx(2.0)


def _full_day_csv(day) -> str:
    lines = ["Read Date and End Time,Read Value"]
    for hour in range(24):
        for minute in (0, 30):
            lines.append(f"{day.strftime('%d-%m-%Y')} {hour:02d}:{minute:02d},0.100")
    return "\n".join(lines) + "\n"


async def test_recent_complete_day(hass, tmp_path):
    from datetime import timedelta

    yesterday = dt_util.now().date() - timedelta(days=1)
    (tmp_path / "y.csv").write_text(_full_day_csv(yesterday), encoding="utf-8")
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["recent_complete_date"] == yesterday
    assert data["recent_complete"]["total_kwh"] == pytest.approx(4.8)  # 48 * 0.1


async def test_prune_keeps_recent_and_backs_up(hass, tmp_path):
    (tmp_path / "multi.csv").write_text(
        "Read Date and End Time,Read Value\n"
        "01-01-2026 12:00,1.000\n"
        "02-01-2026 12:00,1.000\n"
        "03-01-2026 12:00,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    result = await hass.async_add_executor_job(coordinator._prune, 1)
    assert result == {"before": 3, "after": 2, "removed": 1}
    assert (tmp_path / "pruned_backup").is_dir()
    assert (tmp_path / "esb_smart_meter_history.csv").exists()

    # The consolidated file must re-read to exactly the kept rows.
    data = await coordinator._async_update_data()
    assert data["records"] == 2


async def test_time_shift_applied(hass, tmp_path):
    (tmp_path / "s.csv").write_text(
        "Read Date and End Time,Read Value\n01-01-2026 00:00,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass, _entry(tmp_path, **{CONF_TIME_SHIFT_MINUTES: -30})
    )
    readings = coordinator.costed_readings()
    assert len(readings) == 1
    # 00:00 shifted back 30 minutes -> previous day 23:30.
    assert readings[0][0].hour == 23
    assert readings[0][0].minute == 30
