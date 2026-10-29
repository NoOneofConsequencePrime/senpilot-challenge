"""Feasibility spikes G3-G5: download up to N documents of a type, record sizes, time and browser memory.

Usage: python spikes/download.py M12205 "Other Documents" [n=10]
Memory sampling is Windows-only (tasklist); on Linux it is skipped (use `docker stats` there).
"""

import csv
import io
import subprocess
import sys
import threading
import time

from playwright.sync_api import sync_playwright

from common import OUT, open_matter

peak_mb = 0.0
stop = threading.Event()


def sample_memory() -> None:
    """Sum the working set of Playwright's headless Chromium processes once a second."""
    global peak_mb
    while not stop.is_set():
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome-headless-shell.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        ).stdout
        total = 0.0
        for row in csv.reader(io.StringIO(out)):
            if len(row) >= 5 and row[0].lower().startswith("chrome-headless-shell"):
                total += float(row[4].replace(",", "").replace(" K", "").replace("\xa0", "").strip()) / 1024
        peak_mb = max(peak_mb, total)
        time.sleep(1)


def main(matter: str, doc_type: str, n: int) -> None:
    dest = OUT / f"{matter}_{doc_type.replace(' ', '')}"
    dest.mkdir(exist_ok=True)
    if sys.platform == "win32":
        threading.Thread(target=sample_memory, daemon=True).start()
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        open_matter(page, matter)
        page.get_by_role("button", name=f"{doc_type} - ").first.click()
        buttons = page.get_by_text("GO GET IT")
        buttons.first.wait_for(timeout=60_000)
        page.wait_for_timeout(1000)
        print(f"tab ready after {time.time() - t0:.1f}s; visible GO GET IT buttons: {buttons.count()}")

        total_bytes = 0
        for i in range(min(n, buttons.count())):
            t1 = time.time()
            buttons.nth(i).click()
            # Documents open a "Download Files" dialog; media fields (Recordings/Transcripts)
            # open "Export Field to File" first.
            dl_dialog = page.locator(".v-window").filter(has_text="Download Files")
            export_dialog = page.locator(".v-window").filter(has_text="Export Field to File")
            dl_dialog.or_(export_dialog).first.wait_for(timeout=60_000)
            file_button = dl_dialog.locator(".fm-download-button")
            if export_dialog.is_visible():
                print("    export dialog; Save As =", export_dialog.locator("input").first.input_value())
                got: list = []
                page.once("download", lambda d: got.append(d))
                export_dialog.get_by_role("button", name="OK").click()
                # After the export the server either starts the download itself or shows
                # the Download Files dialog; wait for whichever comes first.
                deadline = time.time() + 300
                clicked = False
                while not got and time.time() < deadline:
                    if not clicked and file_button.count() and file_button.first.is_visible():
                        file_button.first.click()
                        clicked = True
                    page.wait_for_timeout(500)
                if not got:
                    raise TimeoutError(f"no download for row {i} after export")
                download = got[0]
            else:
                with page.expect_download(timeout=300_000) as dl_info:
                    file_button.first.click()
                download = dl_info.value
            target = dest / download.suggested_filename
            download.save_as(target)
            size = target.stat().st_size
            total_bytes += size
            with open(target, "rb") as f:
                magic = f.read(12)
            if dl_dialog.is_visible():
                dl_dialog.get_by_role("button", name="Close").click()
                dl_dialog.wait_for(state="hidden", timeout=30_000)
            print(f"  [{i}] {download.suggested_filename:<20} {size / 1e6:7.2f} MB  {magic!r}  {time.time() - t1:5.1f}s")
        browser.close()
    stop.set()
    print(f"total {total_bytes / 1e6:.2f} MB in {time.time() - t0:.1f}s; peak headless Chromium memory {peak_mb:.0f} MB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10)
