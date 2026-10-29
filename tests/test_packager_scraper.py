import csv
import io
import zipfile
from datetime import date, datetime

import pytest
from conftest import make_files, make_result

from uarb_agent.models import DocType, DocumentRow, normalize_matter
from uarb_agent.packager import Delivery, build_zip, choose_delivery, zip_name
from uarb_agent.scraper import ScrapeError, parse_header, parse_row, safe_filename

MB = 1024 * 1024


def test_zip_has_folders_and_manifest(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 3))
    target = tmp_path / "out.zip"
    size = build_zip([result], target)
    assert size == target.stat().st_size
    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
        manifest = list(csv.DictReader(io.StringIO(zf.read("manifest.csv").decode())))
    assert "M12205/Other Documents/1000_Doc 0.pdf" in names
    assert [m["doc_no"] for m in manifest] == ["1000", "1001", "1002"]


def test_zip_name(metadata, counts):
    one = make_result(metadata, counts, [])
    assert zip_name([one], datetime(2026, 1, 2, 3, 4)) == "M12205_Other-Documents.zip"
    assert zip_name([one, one], datetime(2026, 1, 2, 3, 4)) == "uarb-request-20260102-0304.zip"


@pytest.mark.parametrize("size,expected", [
    (1 * MB, Delivery.INLINE),
    (int(4.3 * MB), Delivery.INLINE),
    (7 * MB, Delivery.URL_ATTACHMENT),
    (15 * MB, Delivery.URL_ATTACHMENT),
    (124 * MB, Delivery.LINK_ONLY),
])
def test_choose_delivery(size, expected):
    assert choose_delivery(size, int(4.3 * MB), 15 * MB) is expected


@pytest.mark.parametrize("raw,expected", [("M12205", "M12205"), (" m12205 ", "M12205"), ("12205", "M12205")])
def test_normalize_matter(raw, expected):
    assert normalize_matter(raw) == expected


@pytest.mark.parametrize("raw", ["M1220", "M122055", "X12205", "", "M12205; DROP TABLE"])
def test_normalize_matter_rejects(raw):
    with pytest.raises(ValueError):
        normalize_matter(raw)


def field(text, width=100):
    return {"text": text, "width": width}


def test_parse_document_row():
    row = parse_row({"row": 2, "button": "b0p1o299i2i0r1", "fields": [
        field("102674"), field("Board Order", 1049), field("07/08/2026"), field("Public"), field(".pdf"),
    ]})
    assert (row.doc_no, row.title, row.date, row.ext) == ("102674", "Board Order", date(2026, 7, 8), ".pdf")


def test_parse_recording_row_has_no_doc_number():
    row = parse_row({"row": 1, "button": "b", "fields": [
        field("09/12/2022"), field("M10431 - NS Power 2022 GRA - Monday", 900), field(""),
    ]})
    assert row.doc_no is None and row.date == date(2022, 9, 12)


def test_parse_header():
    md = parse_header(["M12205", "Capital Expenditure Approvals", "Closed", "Title", "04/07/2025", "", "", "Water"],
                      "M12205")
    assert (md.category, md.type, md.date_received, md.date_final) == (
        "Capital Expenditure Approvals", "Water", date(2025, 4, 7), None)


def test_parse_header_rejects_unexpected_layout():
    with pytest.raises(ScrapeError):
        parse_header(["M12205", "a", "b", "c", "not a date", "", "", ""], "M12205")
    with pytest.raises(ScrapeError):
        parse_header(None, "M12205")


def test_safe_filename_strips_unsafe_characters():
    row = DocumentRow(row=1, doc_no="1", title='Letter: "A/B" <draft>?', date=None, ext=".pdf", button_id="b")
    assert safe_filename(row, ".pdf") == "1_Letter_ _A_B_ _draft.pdf"


def test_doc_type_values_match_the_site():
    assert [t.value for t in DocType] == [
        "Exhibits", "Key Documents", "Other Documents", "Transcripts", "Recordings"]
