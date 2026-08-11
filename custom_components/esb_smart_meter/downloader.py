"""ESB Networks CSV downloader.

This is adapted from the public badger707 ESB downloader flow, wrapped as a
callable helper for Home Assistant. ESB applies human-verification and login
rate limits, so this should be scheduled conservatively.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from time import sleep

import requests
from bs4 import BeautifulSoup

# A Firefox UA is deliberate: requests cannot emit the `sec-ch-ua` client hints
# that a real Chrome sends, and a Chrome UA without them is *less* self-consistent
# to Azure B2C's bot detection than a Firefox UA, which never sends them.
USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0"

LOGGER = logging.getLogger(__name__)


class ESBDownloadError(RuntimeError):
    """Raised when the ESB portal download flow fails."""


class ESBCaptchaError(ESBDownloadError):
    """Raised when ESB's B2C flow answers with a captcha challenge.

    This means the account/IP is currently flagged by bot detection; it
    typically clears after several hours with no further login attempts, so the
    caller should back off rather than retry immediately.
    """


@dataclass(frozen=True)
class ESBDownloadResult:
    """Downloaded ESB CSV data."""

    csv_text: str
    filename: str | None
    rows: int


def _raise_for_confirmed_failure(html: str) -> None:
    """Raise a specific error naming why the confirmed step returned no auth form.

    The rendered page carries its own SETTINGS var; its `remoteResource` names
    which B2C page was actually served (captcha, error, login re-render), which
    turns an opaque "login failed" into an actionable reason for the user.
    """
    api = page_mode = None
    remote_resource = ""
    settings_match = re.findall(r"(?<=var SETTINGS = )\S*;", html)
    if settings_match:
        try:
            failed = json.loads(settings_match[0][:-1])
            api = failed.get("api")
            page_mode = failed.get("pageMode")
            remote_resource = failed.get("remoteResource") or ""
        except ValueError:
            pass
    LOGGER.debug("ESB confirmed-step returned no auth form; body: %s", html[:2000])
    if "captcha" in remote_resource.lower():
        raise ESBCaptchaError(
            "ESB login was blocked by a captcha challenge. The account or IP is "
            "currently flagged by bot detection; this usually clears after a few "
            "hours with no further login attempts."
        )
    raise ESBDownloadError(
        "ESB did not complete login (no auth form at the confirmed step; "
        f"rendered page api={api!r} pageMode={page_mode!r}). Human verification "
        "or a login rate limit may be active."
    )


def _logout(session: requests.Session) -> None:
    """Best-effort sign-out so repeated fetches don't pile up server-side sessions.

    /MicrosoftIdentity/Account/SignOut is the portal's Microsoft.Identity.Web
    sign-out route (302 -> B2C /oauth2/v2.0/logout); verified against a real
    browser logout capture. Never allowed to fail the download — the CSV is
    already in hand by the time this runs.
    """
    try:
        session.get(
            "https://myaccount.esbnetworks.ie/MicrosoftIdentity/Account/SignOut",
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
            timeout=(10, 10),
        )
    except requests.RequestException as err:
        LOGGER.debug("ESB sign-out failed (non-fatal): %s", err)


def download_latest_csv(username: str, password: str, mprn: str) -> ESBDownloadResult:
    """Log in to ESB Networks and download interval CSV data."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        response_1 = session.get(
            "https://myaccount.esbnetworks.ie/",
            allow_redirects=True,
            timeout=(10, 10),
        )
        response_1.raise_for_status()
        settings_match = re.findall(r"(?<=var SETTINGS = )\S*;", response_1.text)
        if not settings_match:
            raise ESBDownloadError("ESB login page did not contain expected settings.")
        settings = json.loads(settings_match[0][:-1])
        cookies_1 = session.cookies.get_dict()
        # A real browser sends the B2C authorize-page URL as the Referer on the
        # login XHR and the confirmed navigation.
        authorize_url = response_1.url

        sleep(10)
        response_2 = session.post(
            "https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/"
            "B2C_1A_signup_signin/SelfAsserted?tx="
            + settings["transId"]
            + "&p=B2C_1A_signup_signin",
            data={
                "signInName": username,
                "password": password,
                "request_type": "RESPONSE",
            },
            headers={
                "x-csrf-token": settings["csrf"],
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://login.esbnetworks.ie",
                "Dnt": "1",
                "Sec-Gpc": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            cookies={
                "x-ms-cpim-csrf": cookies_1.get("x-ms-cpim-csrf"),
                "x-ms-cpim-trans": cookies_1.get("x-ms-cpim-trans"),
            },
            allow_redirects=False,
            timeout=(10, 10),
        )
        response_2.raise_for_status()
        cookies_2 = session.cookies.get_dict()

        response_3 = session.get(
            "https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/"
            "B2C_1A_signup_signin/api/CombinedSigninAndSignup/confirmed",
            params={
                # Must be the literal lowercase string "false": a real browser
                # sends it lowercase, and Python's False serialises to "False",
                # which the current B2C flow rejects (it re-renders the page
                # shell instead of returning the token-handoff form).
                "rememberMe": "false",
                "csrf_token": settings["csrf"],
                "tx": settings["transId"],
                "p": "B2C_1A_signup_signin",
                # Client-side diagnostics blob a real browser always appends;
                # B2C uses its presence as a bot signal. pageViewId comes from
                # the same SETTINGS object parsed above.
                "diags": json.dumps(
                    {
                        "pageViewId": settings.get("pageViewId", ""),
                        "pageId": "CombinedSigninAndSignup",
                        "trace": [],
                    },
                    separators=(",", ":"),
                ),
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": authorize_url,
                "Dnt": "1",
                "Sec-Gpc": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
            },
            cookies={
                "x-ms-cpim-csrf": cookies_2.get("x-ms-cpim-csrf"),
                "x-ms-cpim-trans": cookies_2.get("x-ms-cpim-trans"),
            },
            timeout=(10, 10),
        )
        response_3.raise_for_status()

        soup = BeautifulSoup(response_3.content, "html.parser")
        form = soup.find("form", {"id": "auto"})
        if form is None:
            _raise_for_confirmed_failure(response_3.text)

        sleep(2)
        response_4 = session.post(
            form["action"],
            allow_redirects=False,
            data={
                "state": form.find("input", {"name": "state"})["value"],
                "client_info": form.find("input", {"name": "client_info"})["value"],
                "code": form.find("input", {"name": "code"})["value"],
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://login.esbnetworks.ie",
                "Referer": "https://login.esbnetworks.ie/",
                "Dnt": "1",
                "Sec-Gpc": "1",
            },
            timeout=(10, 10),
        )
        response_4.raise_for_status()
        cookies_4 = session.cookies.get_dict()

        response_5 = session.get(
            "https://myaccount.esbnetworks.ie",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://login.esbnetworks.ie/",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
            },
            timeout=(10, 10),
        )
        response_5.raise_for_status()
        cookies_5 = session.cookies.get_dict()

        sleep(3)
        response_6 = session.get(
            "https://myaccount.esbnetworks.ie/Api/HistoricConsumption",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://myaccount.esbnetworks.ie/",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
                ".AspNetCore.Cookies": cookies_5.get(".AspNetCore.Cookies"),
            },
            timeout=(10, 10),
        )
        response_6.raise_for_status()

        response_7 = session.get(
            "https://myaccount.esbnetworks.ie/af/t",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "X-Returnurl": "https://myaccount.esbnetworks.ie/Api/HistoricConsumption",
                "Referer": "https://myaccount.esbnetworks.ie/Api/HistoricConsumption",
            },
            cookies={
                "ARRAffinity": cookies_4.get("ARRAffinity"),
                "ARRAffinitySameSite": cookies_4.get("ARRAffinitySameSite"),
            },
            timeout=(10, 10),
        )
        response_7.raise_for_status()
        token = json.loads(response_7.text)["token"]

        response_8 = session.post(
            "https://myaccount.esbnetworks.ie/DataHub/DownloadHdfPeriodic",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://myaccount.esbnetworks.ie/Api/HistoricConsumption",
                "Content-Type": "application/json",
                "X-Returnurl": "https://myaccount.esbnetworks.ie/Api/HistoricConsumption",
                "X-Xsrf-Token": token,
                "Origin": "https://myaccount.esbnetworks.ie",
            },
            json={"mprn": mprn, "searchType": "intervalkw"},
            timeout=(10, 30),
        )
        response_8.raise_for_status()
        csv_text = response_8.content.decode("utf-8-sig")
        if not csv_text.startswith("MPRN"):
            raise ESBDownloadError("ESB response did not look like an interval CSV.")

        rows = sum(1 for _ in csv.DictReader(csv_text.splitlines()))
        disposition = response_8.headers.get("Content-Disposition")
        filename = None
        if disposition:
            parts = disposition.split(";")
            if len(parts) > 1 and "=" in parts[1]:
                filename = parts[1].split("=", 1)[1].strip().strip('"')
        _logout(session)
        return ESBDownloadResult(csv_text=csv_text, filename=filename, rows=rows)
    except requests.RequestException as err:
        raise ESBDownloadError(f"ESB request failed: {err}") from err
    finally:
        session.close()
