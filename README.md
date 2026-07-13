# ESB Smart Meter for Home Assistant

A Home Assistant custom integration for ESB Networks smart meter CSV exports.
It reads interval CSV files from a local folder and creates sensors for energy
usage, estimated cost, rate buckets, import health, and recent totals.

This integration does not create or manage your ESB Networks account. It is for
people who can already access their ESB Networks smart meter data and want to
turn those CSV exports into Home Assistant sensors.

## Prerequisites

Before installing this integration, set up access to your ESB smart meter data:

1. Create an ESB Networks account at
   [myaccount.esbnetworks.ie](https://myaccount.esbnetworks.ie).
2. Link your electricity meter MPRN in your ESB Networks account.
3. Download one or more smart meter interval CSV exports from ESB Networks.
4. Create a folder in Home Assistant for those CSV files, for example
   `/config/esb_energy`.
5. Copy your ESB CSV exports into that folder.

The ESB account and linked MPRN steps are essential. Without them, you will not
have the interval CSV files this integration reads.

## Features

- Imports ESB interval CSV files from a configured Home Assistant folder.
- Tracks total imported kWh, today's usage, yesterday's usage, monthly usage,
  and the latest interval reading.
- Estimates energy cost using configurable `cheap`, `night`, `day`, and `peak`
  rates, a configurable currency, and an optional daily standing charge.
- **Fully configurable tariff bands** — the cheap/boost, night, day, and peak
  window times are all set to match *your* supplier plan (see below).
- Per-bucket energy and cost breakdowns, a projected month-end cost, and a
  7-day average daily cost.
- Exposes the current rate bucket and current rate as sensors.
- **Optional ESB Networks portal download** — enter your account details and
  Home Assistant can fetch the CSV for you (`esb_smart_meter.download_latest`).
- **Energy dashboard backfill** — import your full CSV history into long-term
  statistics (`esb_smart_meter.import_statistics`).
- Options flow: change paths, tariff bands, and rates any time without
  removing the integration.
- Diagnostics download and a repair issue when no data is found.
- Deduplicates readings by timestamp when multiple CSV files overlap.

## Tariff bands

Electricity plans differ by supplier, so the band **times** and **rates** are
yours to set — during onboarding or later via the integration's options. The
ESB HDF export contains only your half-hourly usage, **not** any pricing or
plan information, so the bands cannot be detected from the data.

The defaults follow the common Irish smart tariff and are contiguous, so every
half-hour falls into exactly one band and `cheap + night + day + peak` always
sums to the total:

| Band  | Default window            | Notes                              |
| ----- | ------------------------- | ---------------------------------- |
| cheap | 02:00–04:00               | Boost/EV window; highest priority  |
| peak  | 17:00–19:00               |                                    |
| night | 23:00–08:00 (wraps)       | Everything from night start to day |
| day   | 08:00–17:00 & 19:00–23:00 | Everything else                    |

Adjust `cheap_start`/`cheap_end`, `night_start`, `day_start`, `peak_start`, and
`peak_end` to match your plan.

## HACS Installation

Use these steps if you already have HACS installed in Home Assistant.

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gerbear1990&repository=ha-esb-smart-meter&category=integration)

1. Click the button above.
2. Choose your Home Assistant instance if prompted.
3. Confirm the repository details:
   - Repository: `gerbear1990/ha-esb-smart-meter`
   - Category: `Integration`
4. Add the repository to HACS.
5. In HACS, download `ESB Smart Meter`.
6. Restart Home Assistant.

This repository does not need to be listed in the default HACS catalog. The
button adds it as a HACS custom repository.

## Home Assistant Integration Setup

After installing the files with HACS or manually, add and configure the
integration in Home Assistant.

[![Open your Home Assistant instance and start configuring this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=esb_smart_meter)

1. Click the button above, or go to **Settings > Devices & services > Add
   integration**.
2. Search for `ESB Smart Meter`.
3. Set the CSV import path, for example `/config/esb_energy`.
4. Set the time shift if your ESB readings need adjusting. The default is
   `-30` minutes.
5. Set your cheap-rate window and unit rates.
6. Submit the form.
7. Check that sensors are created and that the record count is greater than
   zero after valid CSV files are found.

You can rescan the CSV folder at any time by calling the
`esb_smart_meter.reload` service.

## Manual Installation

Use these steps if you do not use HACS.

1. Download or clone this repository.
2. Copy `custom_components/esb_smart_meter` into your Home Assistant
   `custom_components` directory.
3. Restart Home Assistant.
4. Follow the **Home Assistant Integration Setup** steps above.

The final folder should look like this:

```text
config/
  custom_components/
    esb_smart_meter/
      __init__.py
      config_flow.py
      const.py
      coordinator.py
      diagnostics.py
      downloader.py
      manifest.json
      sensor.py
      services.yaml
      statistics.py
      strings.json
      translations/
        en.json
```

## YAML Configuration

The UI setup is recommended, but YAML import is also supported. A sanitized
example is available in `examples/configuration.example.yaml`:

```yaml
esb_smart_meter:
  name: ESB Smart Meter
  import_path: /config/esb_energy
  time_shift_minutes: -30
  currency: EUR
  standing_charge: 0.0        # daily fixed charge, in your currency
  cheap_start: "02:00"
  cheap_end: "04:00"
  night_start: "23:00"
  day_start: "08:00"
  peak_start: "17:00"
  peak_end: "19:00"
  rates:
    cheap: 0.08
    night: 0.18
    day: 0.34
    peak: 0.36
    other: 0.34
```

The UI flow additionally accepts optional ESB portal `username`, `password`,
and `mprn` for the download feature.

If you use YAML, restart Home Assistant after editing `configuration.yaml`.

## CSV Format

The integration expects ESB interval CSV exports with a timestamp column and a
kWh value column. It accepts common column names including:

- `Read Date and End Time`
- `Read Date And End Time`
- `read_date_and_end_time`
- `datetime`
- `timestamp`
- `Read Value`
- `Read Value (kWh)`
- `read_value`
- `kWh`
- `kwh`

Timestamp values are parsed using common ESB-style date formats such as
`DD-MM-YYYY HH:MM`, `YYYY-MM-DD HH:MM`, and ISO timestamps.

## Sensors

The integration creates sensors for:

- Last import time and last reading time.
- Imported record count and coverage days.
- Latest interval energy.
- Total imported energy.
- Today, yesterday, and month energy totals.
- Today, yesterday, and month estimated cost.
- Per-rate totals for current-day usage.
- Current rate bucket and current rate.

Per-bucket energy and cost breakdowns are exposed as attributes on the
`today`/`yesterday`/`month` energy and cost sensors. A projected month-end cost
and a 7-day average daily cost are also provided.

Sensor availability depends on whether valid CSV rows have been imported. Basic
diagnostic sensors remain available even when no CSV data has been found.

## Services

| Service                             | What it does                                             |
| ----------------------------------- | -------------------------------------------------------- |
| `esb_smart_meter.reload`            | Re-scan the CSV folder and refresh all sensors.          |
| `esb_smart_meter.download_latest`          | Log in to ESB Networks and download the latest CSV.      |
| `esb_smart_meter.import_statistics` | Backfill CSV history into the Energy dashboard.          |

## Automatic download (optional)

If you provide your ESB portal email, password, and MPRN during setup, the
`esb_smart_meter.download_latest` service will log in to
[myaccount.esbnetworks.ie](https://myaccount.esbnetworks.ie) and save the latest
interval CSV into your import folder, then refresh the sensors.

> **ESB rate-limits logins heavily** (roughly one or two attempts per day).
> The download is therefore never run automatically on the polling interval —
> trigger it yourself, for example with a once-daily automation:

```yaml
automation:
  - alias: Daily ESB download
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: esb_smart_meter.download_latest
```

## Energy dashboard history

The regular sensors only accrue from the moment you install the integration.
To see your full history on the Energy dashboard, call
`esb_smart_meter.import_statistics` once after importing CSVs. It pushes your
whole CSV history into Home Assistant long-term statistics as external
statistics (`esb_smart_meter:import_energy` and `esb_smart_meter:import_cost`).
Running it again is safe — existing points are updated in place.

## Privacy

Do not commit your real Home Assistant `configuration.yaml`, `secrets.yaml`,
`.storage` directory, database files, logs, or ESB CSV exports. They can contain
account details, meter identifiers, local network addresses, device names, or
usage patterns.

This repository intentionally contains only sanitized source code and example
configuration. It does not include personal meter data, MPRNs, ESB account
credentials, Home Assistant storage, logs, or local network configuration.

## Acknowledgements

This project builds on work and ideas from two public ESB smart meter projects:

- [badger707/esb-smart-meter-reading-automation](https://github.com/badger707/esb-smart-meter-reading-automation)
  by `badger707`, which documented the ESB Networks account and MPRN
  requirements and implemented an ESB Networks smart meter data download flow.
- [raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV](https://github.com/raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV)
  by `raydex79`, which adapted ESB smart meter data processing for Grafana CSV
  workflows.

Thanks to both creators for publishing their work.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, or supported
by ESB Networks or Home Assistant.

## License

Released under the [MIT License](LICENSE).
