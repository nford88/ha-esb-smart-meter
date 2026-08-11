"""Tests for entry setup when the recorder is unavailable.

These live apart from test_statistics.py because that module force-enables a
recorder for every test in it; here the point is that setup survives without
one.
"""

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_IMPORT_PATH,
    CONF_TIME_SHIFT_MINUTES,
    DOMAIN,
)


def _entry(path):
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_PATH: str(path), CONF_TIME_SHIFT_MINUTES: -30},
    )


async def test_setup_without_recorder(hass, tmp_path):
    """Entry setup must not fail when the recorder is not loaded."""
    (tmp_path / "a.csv").write_text(
        "Read Date and End Time,Read Value (kWh)\n01-01-2026 00:30,1.000\n",
        encoding="utf-8",
    )
    entry = _entry(tmp_path)
    entry.add_to_hass(hass)

    # Setting up the entry pulls in the component itself.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id].data["available"] is True
