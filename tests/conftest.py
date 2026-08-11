"""Common fixtures for ESB Smart Meter tests."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# "Read Value" under an ESB HDF export is MEAN POWER in kW over the half-hour
# interval, so the energy each row contributes is half the number below. The
# expectations in the tests are in kWh and account for that.
SAMPLE_CSV = (
    "Read Date and End Time,Read Value\n"
    "01-01-2026 00:30,0.500\n"
    "01-01-2026 01:00,0.700\n"
    "01-01-2026 03:00,0.200\n"  # cheap window (02:00-04:00)
    "01-01-2026 18:00,1.000\n"  # peak (17:00-19:00)
    "01-01-2026 12:00,0.800\n"  # day
)
# 3.2 kW of half-hour means -> 1.6 kWh of energy.
SAMPLE_CSV_KWH = 1.6


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    yield


@pytest.fixture
def csv_dir(tmp_path):
    """Create a folder with one sample ESB CSV file."""
    (tmp_path / "esb.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    return tmp_path
