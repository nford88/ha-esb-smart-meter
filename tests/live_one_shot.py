#!/usr/bin/env python3
"""ONE-SHOT live login test against the real ESB portal.

Drives the actual downloader (download_latest_csv) end-to-end. Run it ONCE and
stop — repeated failed attempts feed Azure B2C's bot detection, which triggers a
multi-hour captcha lockout.

Deliberately NOT named test_* so pytest never collects it.

Usage (from the repo root, with the test venv):
    .venv/bin/python tests/live_one_shot.py <email> <mprn>

Prompts for the password (hidden input, never on the command line).
"""

import getpass
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.esb_smart_meter.downloader import (  # noqa: E402
    ESBCaptchaError,
    ESBDownloadError,
    download_latest_csv,
)


def main(username: str, password: str, mprn: str) -> int:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("urllib3").setLevel(logging.INFO)
    try:
        result = download_latest_csv(username=username, password=password, mprn=mprn)
    except ESBCaptchaError as err:
        print(f"\nCAPTCHA LOCKOUT: {err}", file=sys.stderr)
        return 2
    except ESBDownloadError as err:
        print(f"\nDOWNLOAD FAILED: {err}", file=sys.stderr)
        return 1
    print(f"\nSUCCESS: {result.rows} rows (source filename: {result.filename})")
    lines = result.csv_text.splitlines()
    if len(lines) > 1:
        print(f"  header:    {lines[0]}")
        print(f"  first row: {lines[1]}")
        print(f"  last row:  {lines[-1]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    raise SystemExit(main(sys.argv[1], getpass.getpass("ESB password: "), sys.argv[2]))
