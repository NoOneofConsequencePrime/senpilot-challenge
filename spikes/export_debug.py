"""Debug what happens after OK in the "Export Field to File" dialog (Transcripts tab).

Usage: python spikes/export_debug.py M10431 Transcripts
"""

import sys
import time

from playwright.sync_api import sync_playwright

from common import OUT, open_matter


def main(matter: str, doc_type: str) -> None:
    events: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        page.on("download", lambda d: events.append(f"download {d.suggested_filename}"))
        context.on("page", lambda pg: events.append(f"popup {pg.url}"))
        open_matter(page, matter)
        page.get_by_role("button", name=f"{doc_type} - ").first.click()
        page.get_by_text("GO GET IT").first.wait_for(timeout=60_000)
        page.wait_for_timeout(1000)
        page.get_by_text("GO GET IT").first.click()
        export_dialog = page.locator(".v-window").filter(has_text="Export Field to File")
        export_dialog.wait_for(timeout=60_000)
        export_dialog.get_by_role("button", name="OK").click()
        t0 = time.time()
        for k in range(8):
            page.wait_for_timeout(5000)
            windows = page.locator(".v-window")
            titles = [windows.nth(i).inner_text()[:120].replace("\n", " | ") for i in range(windows.count())]
            print(f"t+{time.time() - t0:4.0f}s windows={titles} events={events}")
            page.screenshot(path=OUT / f"05_export_{k}.png")
            if events:
                break
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
