from datetime import date
from pathlib import Path

import pytest

from uarb_agent.models import DocRequest, DocType, DocumentRow, DownloadedFile, FetchResult, MatterMetadata


@pytest.fixture
def metadata() -> MatterMetadata:
    """The assignment's example matter, as the brief describes it."""
    return MatterMetadata(
        matter="M12205",
        title="Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,270,000",
        type="Water",
        category="Capital Expenditure",
        status="Closed",
        outcome="",
        date_received=date(2025, 4, 7),
        date_final=date(2025, 10, 23),
    )


@pytest.fixture
def counts() -> dict[DocType, int]:
    return {
        DocType.EXHIBITS: 13,
        DocType.KEY_DOCUMENTS: 5,
        DocType.OTHER_DOCUMENTS: 21,
        DocType.TRANSCRIPTS: 0,
        DocType.RECORDINGS: 0,
    }


def make_files(tmp: Path, n: int, size: int = 1000) -> list[DownloadedFile]:
    files = []
    for i in range(n):
        path = tmp / f"{1000 + i}_Doc {i}.pdf"
        path.write_bytes(b"%PDF-" + b"x" * (size - 5))
        row = DocumentRow(row=i + 1, doc_no=str(1000 + i), title=f"Doc {i}", date=date(2025, 5, i + 1),
                          ext=".pdf", button_id=f"b{i}")
        files.append(DownloadedFile(row=row, path=path, size=size))
    return files


def make_result(metadata, counts, files, doc_type=DocType.OTHER_DOCUMENTS, **req) -> FetchResult:
    return FetchResult(request=DocRequest(matter=metadata.matter, doc_type=doc_type, **req),
                       metadata=metadata, counts=counts, files=files)
