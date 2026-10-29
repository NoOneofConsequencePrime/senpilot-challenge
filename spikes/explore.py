"""Feasibility spike G2: can headless Chromium load the UARB WebDirect app and find the search box?

Usage: python spikes/explore.py
Writes screenshots and DOM dumps to spikes/out/.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        t0 = time.time()
        page.goto(URL)
        # WebDirect renders after its websocket handshake; wait for the landing text.
        page.get_by_text("Go Directly to Matter").first.wait_for(timeout=60_000)
        print(f"landing rendered in {time.time() - t0:.1f}s")
        page.screenshot(path=OUT / "01_landing.png", full_page=True)
        (OUT / "01_landing.html").write_text(page.content(), encoding="utf-8")

        inputs = page.locator("input")
        print(f"inputs: {inputs.count()}")
        for i in range(inputs.count()):
            el = inputs.nth(i)
            print(i, el.get_attribute("placeholder"), el.get_attribute("class"), el.is_visible())
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
