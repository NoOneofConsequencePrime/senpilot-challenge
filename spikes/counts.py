"""Print the five tab counts for each matter given (used to find matters with Recordings/Transcripts).

Usage: python spikes/counts.py M10431 M11658 ...
"""

import sys

from playwright.sync_api import sync_playwright

from common import open_matter


def main(matters: list[str]) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for matter in matters:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            try:
                open_matter(page, matter)
                page.wait_for_timeout(800)
                labels = [
                    page.get_by_role("button", name=f"{t} - ").first.inner_text()
                    for t in ("Exhibits", "Key Documents", "Other Documents", "Transcripts", "Recordings")
                ]
                print(matter, " | ".join(labels))
            except Exception as exc:  # spike: report and keep going
                print(matter, "FAILED:", type(exc).__name__, str(exc).splitlines()[0])
                page.screenshot(path=f"out/counts_fail_{matter}.png")
            page.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
