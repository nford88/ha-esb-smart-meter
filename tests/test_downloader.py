"""Offline tests for the ESB portal login/download flow.

A fake requests.Session replays the request/response sequence captured from a
real Chrome login (secrets removed), pinning the request *shape* Azure B2C's
bot detection is sensitive to. No network access.
"""

import json

import pytest

from custom_components.esb_smart_meter import downloader

CSRF = "FAKECSRF=="
TRANS_ID = "StateProperties=eyJUSUQiOiJmYWtlIn0"
PAGE_VIEW_ID = "11111111-2222-3333-4444-555555555555"
AUTHORIZE_URL = (
    "https://login.esbnetworks.ie/esbntwkscustportalprdb2c01.onmicrosoft.com/"
    "b2c_1a_signup_signin/oauth2/v2.0/authorize?client_id=abc&state=xyz"
)


def _settings_page(extra: str = "") -> str:
    """Build a B2C page whose inline SETTINGS var the downloader parses."""
    return (
        "<!DOCTYPE html><html><head><script>"
        'var SETTINGS = {"csrf":"' + CSRF + '","transId":"' + TRANS_ID + '",'
        '"pageViewId":"' + PAGE_VIEW_ID + '","api":"CombinedSigninAndSignup",'
        '"pageMode":1' + extra + "};"
        "</script></head><body></body></html>"
    )


AUTHORIZE_PAGE = _settings_page()

CONFIRMED_OK = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"><html><body>'
    '<form id="auto" method="POST" action="https://myaccount.esbnetworks.ie/signin-oidc">'
    '<input name="state" value="STATE"/>'
    '<input name="client_info" value="CINFO"/>'
    '<input name="code" value="CODE"/>'
    "</form></body></html>"
)

CONFIRMED_CAPTCHA = _settings_page(
    ',"remoteResource":"https://customerportalprdsastd01.blob.core.windows.net'
    '/b2cpages/captcha.html"'
)

CONFIRMED_SHELL = _settings_page()

CSV_TEXT = (
    "MPRN,Meter Serial Number,Read Value,Read Type,Read Date and End Time\r\n"
    "10300000000,000,0.08,Active Import Interval (kW),08-08-2026 13:30\r\n"
    "10300000000,000,0.10,Active Import Interval (kW),08-08-2026 13:00\r\n"
)


class FakeResponse:
    def __init__(self, *, text="", url="", status_code=200, headers=None):
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise downloader.requests.HTTPError(f"HTTP {self.status_code}")


class FakeCookies:
    def __init__(self):
        self._d = {
            "x-ms-cpim-csrf": "c",
            "x-ms-cpim-trans": "t",
            "ARRAffinity": "a",
            "ARRAffinitySameSite": "a2",
            ".AspNetCore.Cookies": "auth",
        }

    def get_dict(self):
        return dict(self._d)


class FakeSession:
    def __init__(self, confirmed_body=CONFIRMED_OK):
        self.headers = {}
        self.cookies = FakeCookies()
        self.requests = []
        self.closed = False
        self._confirmed_body = confirmed_body

    def _record(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))

    def get(self, url, **kwargs):
        self._record("GET", url, kwargs)
        if url == "https://myaccount.esbnetworks.ie/":
            return FakeResponse(text=AUTHORIZE_PAGE, url=AUTHORIZE_URL)
        if "/api/CombinedSigninAndSignup/confirmed" in url:
            return FakeResponse(text=self._confirmed_body, url=url)
        if url == "https://myaccount.esbnetworks.ie":
            return FakeResponse(url=url)
        if url.endswith("/Api/HistoricConsumption"):
            return FakeResponse(url=url)
        if url.endswith("/af/t"):
            return FakeResponse(text='{"token":"XSRF"}', url=url)
        if "/MicrosoftIdentity/Account/SignOut" in url:
            return FakeResponse(url="https://www.esbnetworks.ie/")
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, **kwargs):
        self._record("POST", url, kwargs)
        if "/SelfAsserted" in url:
            return FakeResponse(text='{"status":"200"}', url=url)
        if url.endswith("/signin-oidc"):
            return FakeResponse(url="https://myaccount.esbnetworks.ie/")
        if url.endswith("/DownloadHdfPeriodic"):
            return FakeResponse(
                text=CSV_TEXT,
                url=url,
                headers={"Content-Disposition": 'attachment; filename="HDF.csv"'},
            )
        raise AssertionError(f"unexpected POST {url}")

    def close(self):
        self.closed = True

    def find(self, method, fragment):
        for m, u, kw in self.requests:
            if m == method and fragment in u:
                return u, kw
        raise AssertionError(f"no {method} matching {fragment!r}")

    def has(self, method, fragment):
        return any(m == method and fragment in u for m, u, _ in self.requests)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(downloader, "sleep", lambda *_: None)


def _run(fake, monkeypatch):
    monkeypatch.setattr(downloader.requests, "Session", lambda: fake)
    return downloader.download_latest_csv(
        username="user@example.com", password="pw", mprn="10300000000"
    )


def test_confirmed_request_shape(monkeypatch):
    fake = FakeSession()
    _run(fake, monkeypatch)
    _, kw = fake.find("GET", "/api/CombinedSigninAndSignup/confirmed")
    params = kw["params"]
    # THE fix: lowercase string, never Python False -> "False"
    assert params["rememberMe"] == "false"
    assert isinstance(params["rememberMe"], str)
    diags = json.loads(params["diags"])
    assert diags["pageViewId"] == PAGE_VIEW_ID
    assert diags["pageId"] == "CombinedSigninAndSignup"
    assert kw["headers"]["Referer"] == AUTHORIZE_URL


def test_selfasserted_headers(monkeypatch):
    fake = FakeSession()
    _run(fake, monkeypatch)
    _, kw = fake.find("POST", "/SelfAsserted")
    headers = kw["headers"]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Origin"] == "https://login.esbnetworks.ie"


def test_successful_download_and_logout(monkeypatch):
    fake = FakeSession()
    result = _run(fake, monkeypatch)
    assert result.rows == 2
    assert result.filename == "HDF.csv"
    # sign-out fired after the CSV download, and the session was closed
    assert fake.has("GET", "/MicrosoftIdentity/Account/SignOut")
    assert fake.closed


def test_captcha_page_raises_specific_error(monkeypatch):
    fake = FakeSession(confirmed_body=CONFIRMED_CAPTCHA)
    with pytest.raises(downloader.ESBCaptchaError) as excinfo:
        _run(fake, monkeypatch)
    assert "captcha" in str(excinfo.value).lower()


def test_login_shell_raises_download_error_with_page_identity(monkeypatch):
    fake = FakeSession(confirmed_body=CONFIRMED_SHELL)
    with pytest.raises(downloader.ESBDownloadError) as excinfo:
        _run(fake, monkeypatch)
    message = str(excinfo.value)
    assert "did not complete login" in message
    assert "CombinedSigninAndSignup" in message
    # a plain shell is not a captcha
    assert not isinstance(excinfo.value, downloader.ESBCaptchaError)
