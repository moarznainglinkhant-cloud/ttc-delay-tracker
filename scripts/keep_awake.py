"""
Keep the Streamlit Community Cloud app awake.

Community Cloud puts an app to sleep after 12 hours without visitors, and
a plain HTTP request doesn't count: it gets a static page back while the
app stays asleep. So this opens the app in a real (headless) browser,
which counts as a visit, and clicks "Yes, get this app back up!" if the
app has already gone to sleep.

Run by .github/workflows/keep-awake.yml every few hours. Locally:
    pip install playwright && playwright install chromium
    python scripts/keep_awake.py [URL ...]

Exits non-zero if an app is still asleep at the end, so a failed run
shows red in the Actions tab.
"""
from __future__ import annotations

import re
import sys

from playwright.sync_api import Page, sync_playwright

DEFAULT_URLS = ["https://ttc-delay-tracker-56pbzhwscg9z9k7tbuyzlm.streamlit.app/"]

WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
PAGE_LOAD_MS = 90_000
WAKE_TIMEOUT_MS = 240_000  # a cold start can take a few minutes


def wake_button(page: Page):
    return page.get_by_role("button", name=WAKE_BUTTON)


def app_has_rendered(page: Page) -> bool:
    """True once Streamlit has drawn the app, inside or outside the iframe."""
    for frame in page.frames:
        try:
            if frame.locator('[data-testid="stAppViewContainer"]').count() > 0:
                return True
        except Exception:  # frame detached mid-check
            continue
    return False


def visit(page: Page, url: str) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

    # Give the page a moment to decide whether it's the app or the sleep screen.
    for _ in range(30):
        if wake_button(page).count() > 0 or app_has_rendered(page):
            break
        page.wait_for_timeout(1_000)

    if wake_button(page).count() == 0:
        return "awake" if app_has_rendered(page) else "unknown"

    print("  asleep, clicking the wake button ...", flush=True)
    wake_button(page).first.click()

    waited = 0
    while waited < WAKE_TIMEOUT_MS:
        page.wait_for_timeout(5_000)
        waited += 5_000
        if app_has_rendered(page):
            return "woken"
    return "still asleep"


def main(urls: list[str]) -> int:
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for url in urls:
            page = browser.new_page()
            try:
                status = visit(page, url)
            except Exception as exc:  # network error, timeout, etc.
                status = f"error: {str(exc).splitlines()[0]}"
            finally:
                page.close()
            print(f"{status:14s} {url}", flush=True)
            if status == "still asleep" or status.startswith("error"):
                failures += 1
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or DEFAULT_URLS))
