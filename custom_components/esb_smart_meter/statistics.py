"""Backfill ESB history into Home Assistant long-term statistics.

The regular sensors only accrue from the moment the integration is set up.
Because ESB CSV exports contain months of half-hourly history, we can push
that history straight into the recorder as *external* statistics so it shows
up on the Energy dashboard with the correct dates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .const import DOMAIN, STAT_COST_SUFFIX, STAT_ENERGY_SUFFIX
from .coordinator import ESBSmartMeterCoordinator

LOGGER = logging.getLogger(__name__)


async def async_backfill_statistics(
    hass: HomeAssistant, coordinator: ESBSmartMeterCoordinator
) -> int:
    """Import all available CSV history as external statistics.

    Returns the number of hourly statistic points written per metric.
    """
    readings = await hass.async_add_executor_job(coordinator.costed_readings)
    if not readings:
        LOGGER.warning("ESB statistics backfill found no readings to import")
        return 0

    energy_stats, cost_stats = _build_hourly(readings)

    energy_id = f"{DOMAIN}:{STAT_ENERGY_SUFFIX}"
    cost_id = f"{DOMAIN}:{STAT_COST_SUFFIX}"

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{coordinator.name} imported energy",
            source=DOMAIN,
            statistic_id=energy_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        ),
        energy_stats,
    )
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{coordinator.name} imported cost",
            source=DOMAIN,
            statistic_id=cost_id,
            unit_of_measurement=coordinator.currency,
        ),
        cost_stats,
    )
    LOGGER.info(
        "ESB statistics backfill wrote %s hourly points to %s and %s",
        len(energy_stats),
        energy_id,
        cost_id,
    )
    return len(energy_stats)


def _build_hourly(
    readings: list[tuple[datetime, float, float]],
) -> tuple[list[StatisticData], list[StatisticData]]:
    """Aggregate half-hourly readings into cumulative hourly statistics."""
    hourly_energy: dict[datetime, float] = defaultdict(float)
    hourly_cost: dict[datetime, float] = defaultdict(float)
    for when, kwh, cost in readings:
        hour = when.replace(minute=0, second=0, microsecond=0)
        hourly_energy[hour] += kwh
        hourly_cost[hour] += cost

    energy_stats: list[StatisticData] = []
    cost_stats: list[StatisticData] = []
    running_energy = 0.0
    running_cost = 0.0
    for hour in sorted(hourly_energy):
        running_energy += hourly_energy[hour]
        running_cost += hourly_cost[hour]
        energy_stats.append(
            StatisticData(start=hour, state=round(hourly_energy[hour], 3),
                          sum=round(running_energy, 3))
        )
        cost_stats.append(
            StatisticData(start=hour, state=round(hourly_cost[hour], 4),
                          sum=round(running_cost, 4))
        )
    return energy_stats, cost_stats
