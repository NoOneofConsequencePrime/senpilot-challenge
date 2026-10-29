"""Feasibility spike G2: search a matter via "Go Directly to Matter" and dump the matter page.

Usage: python spikes/matter.py M12205
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def main(matter: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        t0 = time.time()
        page.goto(URL)
        prompt = page.get_by_text("eg M01234", exact=True)
        prompt.wait_for(timeout=60_000)
        # FileMaker overlays a transparent div on its fields, so click the screen
        # position like a user would instead of the element itself.
        box = prompt.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)
        page.keyboard.type(matter)
        page.wait_for_timeout(300)
        # The "Go Directly to Matter" Search button sits right of the input; pick the
        # Search button vertically closest to the input.
        buttons = page.get_by_role("button", name="Search", exact=True)
        best = min(
            (buttons.nth(i) for i in range(buttons.count())),
            key=lambda b: abs(b.bounding_box()["y"] - box["y"]),
        )
        best.click()
        page.get_by_text("Back to Search Results").first.wait_for(timeout=60_000)
        print(f"matter page rendered in {time.time() - t0:.1f}s")
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT / f"02_{matter}.png", full_page=True)
        (OUT / f"02_{matter}.html").write_text(page.content(), encoding="utf-8")
        (OUT / f"02_{matter}.txt").write_text(page.inner_text("body"), encoding="utf-8")
        print(page.inner_text("body")[:3000])
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "M12205")
