"""Feasibility spike G3 (part 1): open a document tab and dump its rows and DOM.

Usage: python spikes/tab.py M12205 "Other Documents"
"""

import sys
import time

from playwright.sync_api import sync_playwright

from common import OUT, open_matter


def main(matter: str, doc_type: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        t0 = time.time()
        open_matter(page, matter)
        page.get_by_role("button", name=f"{doc_type} - ").first.click()
        page.get_by_text("GO GET IT").first.wait_for(timeout=60_000)
        print(f"tab rendered in {time.time() - t0:.1f}s")
        page.wait_for_timeout(1500)
        tag = doc_type.replace(" ", "")
        page.screenshot(path=OUT / f"03_{matter}_{tag}.png", full_page=True)
        (OUT / f"03_{matter}_{tag}.html").write_text(page.content(), encoding="utf-8")
        (OUT / f"03_{matter}_{tag}.txt").write_text(page.inner_text("body"), encoding="utf-8")
        print("GO GET IT buttons:", page.get_by_text("GO GET IT").count())
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
