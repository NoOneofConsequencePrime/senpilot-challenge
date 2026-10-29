"""Drives the UARB public documents site (FileMaker WebDirect) with headless Chromium.

The site is a JavaScript app over a websocket, so plain HTTP can't read it. We follow the same clicks a
person would: Go Directly to Matter -> Search -> tab -> GO GET IT per row.

Site quirks handled here (found during the feasibility spikes):
- FileMaker lays transparent divs over its fields, so the matter box is clicked by screen position.
- Tab counts can render a moment after the page; we wait until all five show a number.
- Documents open a "Download Files" dialog; Transcripts/Recordings open "Export Field to File" first.
- The server sends two Content-Disposition headers when a filename contains a comma, and Chromium
  refuses such downloads. So we intercept the file URL and stream it ourselves with the session
  cookies. That also keeps 300+ MB recordings out of memory.
"""

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, sync_playwright

from .models import DocRequest, DocType, DocumentRow, DownloadedFile, FetchResult, MatterMetadata

log = logging.getLogger(__name__)

URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
TAB_RE = re.compile(r"^(" + "|".join(t.value for t in DocType) + r") - (\d+)$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
TIMEOUT_MS = 60_000
FILE_TIMEOUT_S = 300  # server-side export of a large recording can take minutes
ATTEMPTS = 3

# Header values in DOM order, starting at the matter number. Same order on every layout we've seen.
HEADER_JS = """(matter) => {
  const els = document.querySelectorAll('.fm-textarea[id^="b0p0o"], .v-label[id^="b0p0o"]');
  const texts = Array.from(els, e => e.innerText.trim());
  const i = texts.indexOf(matter);
  return i < 0 ? null : texts.slice(i, i + 8);
}"""

# One entry per GO GET IT button: the row's fields share the button's portal row index (`i<k>` in the id).
ROWS_JS = """() => Array.from(document.querySelectorAll('button[id^="b0p"]'))
  .filter(b => b.innerText.trim() === 'GO GET IT')
  .map(b => {
    const [, p, k] = b.id.match(/^b0p(\\d+)o\\d+i(\\d+)i/);
    const re = new RegExp('^b0p' + p + 'o\\\\d+i' + k + 'i0r\\\\d+$');
    const fields = Array.from(document.querySelectorAll('.fm-textarea[id^="b0p"]'))
      .filter(e => re.test(e.id))
      .map(e => ({text: e.innerText.trim(), width: e.getBoundingClientRect().width}));
    return {row: Number(k), button: b.id, fields};
  })"""


class MatterNotFound(Exception):
    pass


class ScrapeError(Exception):
    pass


class OverBudget(Exception):
    """The next recording would exceed the per-request size budget."""


def parse_date(text: str) -> date | None:
    return datetime.strptime(text, "%m/%d/%Y").date() if DATE_RE.match(text) else None


def parse_row(raw: dict) -> DocumentRow:
    """Classify a row's field texts: the widest field is the title; others by shape."""
    fields = raw["fields"]
    if not fields:
        raise ScrapeError(f"row {raw['row']} has no fields")
    title = max(fields, key=lambda f: f["width"])["text"]
    others = [f["text"] for f in fields if f["text"] != title]
    return DocumentRow(
        row=raw["row"],
        doc_no=next((t for t in others if re.fullmatch(r"\d{3,}", t)), None),
        title=title,
        date=next((parse_date(t) for t in others if DATE_RE.match(t)), None),
        ext=next((t.lower() for t in others if re.fullmatch(r"\.\w{1,5}", t)), None),
        button_id=raw["button"],
    )


def parse_header(texts: list[str] | None, matter: str) -> MatterMetadata:
    if not texts or len(texts) != 8:
        raise ScrapeError(f"could not read the header fields for {matter}: {texts!r}")
    _, category, status, title, received, final, outcome, type_ = texts
    for value in (received, final):
        if value and not DATE_RE.match(value):
            raise ScrapeError(f"unexpected header layout for {matter}: {texts!r}")
    if not title:
        raise ScrapeError(f"empty title for {matter}: {texts!r}")
    return MatterMetadata(
        matter=matter,
        title=title,
        type=type_,
        category=category,
        status=status,
        outcome=outcome,
        date_received=parse_date(received),
        date_final=parse_date(final),
    )


def safe_filename(row: DocumentRow, ext: str) -> str:
    prefix = row.doc_no or (row.date.isoformat() if row.date else f"row{row.row}")
    title = UNSAFE_CHARS.sub("_", row.title).strip(" ._")[:90]
    return f"{prefix}_{title}{ext}"


class UarbScraper:
    def __init__(self, recordings_budget_bytes: int):
        self.recordings_budget = recordings_budget_bytes

    def fetch(self, req: DocRequest, dest: Path) -> FetchResult:
        """Open the matter, read metadata and counts, download up to req.limit files into dest."""
        dest.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            try:
                context = browser.new_context(viewport={"width": 1400, "height": 1000})
                context.set_default_timeout(TIMEOUT_MS)
                page = context.new_page()
                self._open_matter(page, req.matter)
                counts = self._read_counts(page)
                metadata = parse_header(self._read_header(page, req.matter), req.matter)
                result = FetchResult(request=req, metadata=metadata, counts=counts)
                if counts[req.doc_type]:
                    self._open_tab(page, req.doc_type)
                    rendered = [parse_row(r) for r in page.evaluate(ROWS_JS)]
                    if req.start > len(rendered):
                        raise ScrapeError(
                            f"position {req.start} is beyond the {len(rendered)} rows the site shows without scrolling"
                        )
                    rows = rendered[req.start - 1 : req.start - 1 + req.limit]
                    log.info("rows", extra={"matter": req.matter, "type": req.doc_type.value, "rows": len(rows)})
                    self._download_all(page, rows, req.doc_type, dest, result)
                return result
            finally:
                browser.close()  # also ends the site session

    def _open_matter(self, page: Page, matter: str) -> None:
        page.goto(URL)
        prompt = page.get_by_text("eg M01234", exact=True)
        prompt.wait_for()
        box = prompt.bounding_box()  # read before typing: the placeholder disappears afterwards
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)
        page.keyboard.type(matter)
        page.wait_for_timeout(300)
        # The "Go Directly to Matter" Search button is the one level with the matter box.
        buttons = page.get_by_role("button", name="Search", exact=True)
        nearest = min(
            (buttons.nth(i) for i in range(buttons.count())),
            key=lambda b: abs(b.bounding_box()["y"] - box["y"]),
        )
        nearest.click()
        found = page.get_by_text("Back to Search Results").first
        missing = page.get_by_text("No Records Found", exact=True)
        found.or_(missing).first.wait_for()
        if missing.is_visible():
            raise MatterNotFound(matter)

    def _read_counts(self, page: Page) -> dict[DocType, int]:
        deadline = time.time() + TIMEOUT_MS / 1000
        while True:
            labels = page.evaluate(
                "() => Array.from(document.querySelectorAll('.fm-text-character'), e => e.textContent.trim())"
            )
            counts = {DocType(m[1]): int(m[2]) for m in map(TAB_RE.match, labels) if m}
            if len(counts) == len(DocType):
                return counts
            if time.time() > deadline:
                raise ScrapeError(f"tab counts did not render; saw {counts}")
            page.wait_for_timeout(500)

    def _read_header(self, page: Page, matter: str) -> list[str] | None:
        """Header fields render separately from the tabs; poll until the matter number shows up."""
        deadline = time.time() + TIMEOUT_MS / 1000
        while (texts := page.evaluate(HEADER_JS, matter)) is None and time.time() < deadline:
            page.wait_for_timeout(500)
        return texts

    def _open_tab(self, page: Page, doc_type: DocType) -> None:
        page.get_by_role("button", name=f"{doc_type.value} - ").first.click()
        page.get_by_text("GO GET IT").first.wait_for()
        page.wait_for_timeout(1000)  # let the remaining rows render

    def _download_all(self, page: Page, rows: list[DocumentRow], doc_type: DocType, dest: Path, result: FetchResult):
        captured: list[str] = []

        def intercept(route: Route) -> None:
            captured.append(route.request.url)
            route.abort()

        page.context.route("**/dl/**", intercept)
        session = {
            "cookies": {c["name"]: c["value"] for c in page.context.cookies()},
            "headers": {"User-Agent": page.evaluate("navigator.userAgent"), "Referer": URL},
        }
        budget = self.recordings_budget if doc_type is DocType.RECORDINGS else None
        used = 0
        for i, row in enumerate(rows):
            label = row.doc_no or row.title
            error = None
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    captured.clear()
                    url = self._request_file_url(page, row, captured)
                    remaining = None if budget is None else budget - used
                    downloaded = self._stream(url, session, dest, row, remaining)
                    self._dismiss_dialogs(page)
                    break
                except OverBudget:
                    result.skipped_for_size = len(rows) - i
                    log.info("recordings budget reached", extra={"used": used, "skipped": result.skipped_for_size})
                    return
                except (PlaywrightError, httpx.HTTPError, ScrapeError) as exc:
                    error = exc
                    log.warning("download attempt failed", extra={"doc": label, "attempt": attempt, "error": str(exc)})
                    self._dismiss_dialogs(page)
            else:
                result.failures.append(f"{label}: could not download ({type(error).__name__})")
                continue
            used += downloaded.size
            result.files.append(downloaded)

    def _request_file_url(self, page: Page, row: DocumentRow, captured: list[str]) -> str:
        """Click GO GET IT, get through the dialogs, return the file URL the site tries to download."""
        page.locator(f"#{row.button_id}").click()
        dl_dialog = page.locator(".v-window").filter(has_text="Download Files")
        export_dialog = page.locator(".v-window").filter(has_text="Export Field to File")
        dl_dialog.or_(export_dialog).first.wait_for()
        if export_dialog.is_visible():
            export_dialog.get_by_role("button", name="OK").click()
        file_button = dl_dialog.locator(".fm-download-button")
        deadline = time.time() + FILE_TIMEOUT_S
        clicked = False
        # After an export the server either starts the download itself or shows Download Files.
        while not captured:
            if not clicked and file_button.count() and file_button.first.is_visible():
                file_button.first.click()
                clicked = True
            if time.time() > deadline:
                raise ScrapeError(f"no file URL for row {row.row} after {FILE_TIMEOUT_S}s")
            page.wait_for_timeout(300)
        return captured[0]  # valid only while the Download Files dialog stays open

    def _dismiss_dialogs(self, page: Page) -> None:
        dialog = page.locator(".v-window").filter(has_text="Download Files")
        if dialog.is_visible():
            dialog.get_by_role("button", name="Close").click()
            dialog.wait_for(state="hidden")

    def _stream(self, url: str, session: dict, dest: Path, row: DocumentRow, remaining: int | None) -> DownloadedFile:
        ext = Path(unquote(urlparse(url).path)).suffix.lower() or (row.ext or "")
        target = dest / safe_filename(row, ext)
        n = 2
        while target.exists():
            target = target.with_stem(f"{target.stem} ({n})")
            n += 1
        timeout = httpx.Timeout(60, read=120)
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True, **session) as resp:
            resp.raise_for_status()
            length = int(resp.headers.get("content-length") or 0)
            if remaining is not None and length > remaining and remaining < self.recordings_budget:
                raise OverBudget  # always allow the first recording, even if it alone exceeds the budget
            size = 0
            with open(target, "wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    f.write(chunk)
                    size += len(chunk)
        if length and size != length:
            target.unlink()
            raise ScrapeError(f"truncated download for row {row.row}: {size} of {length} bytes")
        log.info("downloaded", extra={"file": target.name, "bytes": size})
        return DownloadedFile(row=row, path=target, size=size)

