"""Builds the reply ZIP (documents + manifest.csv) and decides how it travels by email."""

import csv
import io
import zipfile
from datetime import datetime
from enum import Enum
from pathlib import Path

from .models import FetchResult

# Already-compressed formats: deflating them costs CPU on the small VM for ~no size gain.
STORED_EXTS = {".mp3", ".mp4", ".m4a", ".wav", ".zip", ".jpg", ".jpeg", ".png"}


class Delivery(str, Enum):
    INLINE = "inline"  # base64 in the AgentMail request
    URL_ATTACHMENT = "url_attachment"  # AgentMail fetches it from our presigned link and attaches it
    LINK_ONLY = "link_only"  # too big for recipients' mail servers; link in the email body


def zip_name(results: list[FetchResult], now: datetime) -> str:
    if len(results) == 1:
        r = results[0].request
        return f"{r.matter}_{r.doc_type.value.replace(' ', '-')}.zip"
    return f"uarb-request-{now:%Y%m%d-%H%M}.zip"


def build_zip(results: list[FetchResult], target: Path) -> int:
    """Write <matter>/<doc type>/<file> entries plus manifest.csv; return the ZIP size in bytes."""
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["matter", "document_type", "doc_no", "title", "date", "file", "bytes"])
    with zipfile.ZipFile(target, "w") as zf:
        for result in results:
            folder = f"{result.request.matter}/{result.request.doc_type.value}"
            for f in result.files:
                arcname = f"{folder}/{f.path.name}"
                method = zipfile.ZIP_STORED if f.path.suffix.lower() in STORED_EXTS else zipfile.ZIP_DEFLATED
                zf.write(f.path, arcname, compress_type=method)
                writer.writerow([
                    result.request.matter, result.request.doc_type.value, f.row.doc_no or "", f.row.title,
                    f.row.date.isoformat() if f.row.date else "", arcname, f.size,
                ])
        zf.writestr("manifest.csv", manifest.getvalue())
    return target.stat().st_size


def choose_delivery(size: int, inline_max: int, attach_max: int) -> Delivery:
    if size <= inline_max:
        return Delivery.INLINE
    if size <= attach_max:
        return Delivery.URL_ATTACHMENT
    return Delivery.LINK_ONLY
