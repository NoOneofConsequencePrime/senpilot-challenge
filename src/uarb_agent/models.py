"""Domain types shared across the agent."""

import re
from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

MATTER_RE = re.compile(r"^M\d{5}$")
MAX_FILES = 10


class DocType(str, Enum):
    EXHIBITS = "Exhibits"
    KEY_DOCUMENTS = "Key Documents"
    OTHER_DOCUMENTS = "Other Documents"
    TRANSCRIPTS = "Transcripts"
    RECORDINGS = "Recordings"


def normalize_matter(raw: str) -> str:
    """'m12205' / ' M12205 ' / '12205' -> 'M12205'. Raises ValueError for anything else."""
    value = raw.strip().upper()
    if re.fullmatch(r"\d{5}", value):
        value = "M" + value
    if not MATTER_RE.match(value):
        raise ValueError(f"not a matter number (M + 5 digits): {raw!r}")
    return value


class DocRequest(BaseModel):
    matter: str
    doc_type: DocType
    # The site lists newest first; we take the first `limit` rows.
    limit: int = Field(default=MAX_FILES, ge=1, le=MAX_FILES)

    @field_validator("matter")
    @classmethod
    def _matter(cls, v: str) -> str:
        return normalize_matter(v)


class ParsedEmail(BaseModel):
    requests: list[DocRequest] = Field(default_factory=list)
    clarification_needed: str | None = None
    # Set when the user asked for more than MAX_FILES or more requests than we serve per email.
    notes: list[str] = Field(default_factory=list)


class MatterMetadata(BaseModel):
    matter: str
    title: str
    type: str
    category: str
    status: str
    outcome: str
    date_received: date | None
    date_final: date | None


class DocumentRow(BaseModel):
    row: int  # FileMaker portal row index (1-based), ties fields to their GO GET IT button
    doc_no: str | None  # Recordings have no document number
    title: str
    date: date | None
    ext: str | None
    button_id: str = Field(exclude=True)  # DOM id of the row's GO GET IT button


class DownloadedFile(BaseModel):
    row: DocumentRow
    path: Path
    size: int


class FetchResult(BaseModel):
    request: DocRequest
    metadata: MatterMetadata
    counts: dict[DocType, int]
    files: list[DownloadedFile] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)  # human-readable, shown in the reply
    skipped_for_size: int = 0  # Recordings beyond the per-request size budget
