from __future__ import annotations

import pytest

from tests.fake_gateway import FakeNchito, ServerThread
from tests.webfixtures import CV_BYTES, WebFixtures


def _browser_available() -> str | None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return None
    except Exception as exc:  # browsers not installed, or cannot launch here
        return f"Playwright Chromium is not available here ({type(exc).__name__}); run `playwright install chromium`"


_BROWSER_PROBLEM = _browser_available()


def pytest_collection_modifyitems(config, items):
    if _BROWSER_PROBLEM:
        skip = pytest.mark.skip(reason=_BROWSER_PROBLEM)
        for item in items:
            if "browser" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def web():
    w = WebFixtures()
    w.start()
    yield w
    w.stop()


@pytest.fixture(scope="session")
def _gateway_server():
    fake = FakeNchito()
    srv = ServerThread(fake)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def fake(_gateway_server):
    _gateway_server.fake.reset()
    _gateway_server.fake.files["f-cv"] = CV_BYTES
    return _gateway_server.fake


@pytest.fixture
def gw_url(_gateway_server):
    return _gateway_server.url


@pytest.fixture(autouse=True)
def _reset_web(web):
    web.reset()
