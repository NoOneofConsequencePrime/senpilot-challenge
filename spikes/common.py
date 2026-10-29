"""Shared helpers for the feasibility spikes."""

import sys
from pathlib import Path

from playwright.sync_api import Page

URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

# Windows consoles default to a legacy codepage; the site uses non-ASCII characters.
sys.stdout.reconfigure(encoding="utf-8")


def click_center(page: Page, locator) -> None:
    """Click the screen position of an element (FileMaker overlays transparent divs on fields)."""
    box = locator.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def open_matter(page: Page, matter: str) -> None:
    """Landing page -> type matter into 'Go Directly to Matter' -> Search -> wait for matter page."""
    page.goto(URL)
    prompt = page.get_by_text("eg M01234", exact=True)
    prompt.wait_for(timeout=60_000)
    box = prompt.bounding_box()  # read before typing: the placeholder disappears afterwards
    click_center(page, prompt)
    page.wait_for_timeout(300)
    page.keyboard.type(matter)
    page.wait_for_timeout(300)
    buttons = page.get_by_role("button", name="Search", exact=True)
    nearest = min(
        (buttons.nth(i) for i in range(buttons.count())),
        key=lambda b: abs(b.bounding_box()["y"] - box["y"]),
    )
    nearest.click()
    page.get_by_text("Back to Search Results").first.wait_for(timeout=60_000)
