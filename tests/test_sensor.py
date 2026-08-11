"""Tests for the sensor platform's shape.

These guard the wiring rather than the arithmetic: that every declared sensor
has a translated name, and that the per-band sensor sets are complete. The
missing "Month peak cost" sensor shipped unnoticed because nothing checked the
bands were symmetric.
"""

import json
import pathlib

import pytest

from custom_components.esb_smart_meter.const import RATE_BUCKETS
from custom_components.esb_smart_meter.sensor import EXPORT_SENSORS, SENSORS

_COMPONENT = pathlib.Path(__file__).parents[1] / "custom_components" / "esb_smart_meter"


def _names() -> dict:
    data = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    return data["entity"]["sensor"]


def test_every_sensor_has_a_translated_name():
    names = _names()
    missing = [
        d.translation_key
        for d in (*SENSORS, *EXPORT_SENSORS)
        if d.translation_key not in names
    ]
    assert missing == []


def test_no_orphaned_translation_entries():
    declared = {d.translation_key for d in (*SENSORS, *EXPORT_SENSORS)}
    assert sorted(set(_names()) - declared) == []


def test_translations_match_strings():
    strings = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads(
        (_COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert strings == en


def test_sensor_keys_are_unique():
    keys = [d.key for d in (*SENSORS, *EXPORT_SENSORS)]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("prefix", "suffix"),
    [
        ("today", "energy"),
        ("month", "cost"),
        ("recent_complete", "energy"),
        ("recent_complete", "cost"),
    ],
)
def test_rate_band_sensor_sets_are_complete(prefix, suffix):
    """If one band gets a sensor for a period, all four must."""
    keys = {d.key for d in SENSORS}
    present = {b for b in RATE_BUCKETS if f"{prefix}_{b}_{suffix}" in keys}
    assert present == set(RATE_BUCKETS), (
        f"{prefix}_*_{suffix} is missing: {sorted(set(RATE_BUCKETS) - present)}"
    )
