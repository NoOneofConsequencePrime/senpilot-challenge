"""Feasibility spike G3 (part 2): what does "GO GET IT" deliver? Download event, popup, or a response?

Usage: python spikes/getit.py M12205 "Other Documents" [row_index]
"""

import sys
import time

from playwright.sync_api import sync_playwright

from common import OUT, open_matter


def main(matter: str, doc_type: str, row: int) -> None:
    events: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        open_matter(page, matter)
        page.get_by_role("button", name=f"{doc_type} - ").first.click()
        page.get_by_text("GO GET IT").first.wait_for(timeout=60_000)
        page.wait_for_timeout(1000)

        downloads = []
        popups = []
        page.on("download", lambda d: (downloads.append(d), events.append(f"download: {d.suggested_filename}")))
        context.on("page", lambda pg: (popups.append(pg), events.append(f"popup: {pg.url}")))

        def on_response(resp):
            ctype = resp.headers.get("content-type", "")
            if "websocket" in ctype or "vaadin" in resp.url.lower() and "UIDL" in resp.url:
                return
            events.append(f"response {resp.status} {ctype} {resp.url[:160]}")

        context.on("response", on_response)

        t0 = time.time()
        page.get_by_text("GO GET IT").nth(row).click()
        page.wait_for_timeout(15_000)
        print(f"waited {time.time() - t0:.1f}s; events:")
        for e in events:
            print("  ", e)

        for d in downloads:
            target = OUT / f"dl_{d.suggested_filename}"
            d.save_as(target)
            print("saved download:", target, target.stat().st_size, "bytes")
        for pg in popups:
            print("popup final url:", pg.url)
        page.screenshot(path=OUT / "04_after_getit.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
