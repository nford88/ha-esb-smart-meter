"""Diagnostics support for ESB Smart Meter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MPRN, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import ESBSmartMeterCoordinator

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_MPRN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (sensitive fields redacted)."""
    coordinator: ESBSmartMeterCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "settings": {
            "import_path": str(coordinator.import_path),
            "time_shift": coordinator.time_shift,
            "cheap_start": str(coordinator.cheap_start),
            "cheap_end": str(coordinator.cheap_end),
            "night_start": str(coordinator.night_start),
            "day_start": str(coordinator.day_start),
            "peak_start": str(coordinator.peak_start),
            "peak_end": str(coordinator.peak_end),
            "currency": coordinator.currency,
            "standing_charge": coordinator.standing_charge,
            "rates": coordinator.rates,
            "download_configured": coordinator.has_download_credentials(),
        },
        "data": coordinator.data,
    }
