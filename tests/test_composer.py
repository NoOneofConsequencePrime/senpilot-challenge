from datetime import date

import pytest
from conftest import make_files, make_result

from uarb_agent.composer import (
    Notice,
    ReplyParts,
    compose_ack,
    compose_result,
    counts_sentence,
    download_sentence,
    first_name,
    fmt_size,
)
from uarb_agent.models import DocRequest, DocType
from uarb_agent.packager import Delivery


def test_reproduces_the_briefs_example(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 10))
    reply = compose_result(ReplyParts(results=[result], delivery=Delivery.INLINE, zip_size=10_000,
                                      link="https://x/y.zip", job_id="j1"))
    assert (
        "M12205 is about the Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - "
        "$69,270,000. It relates to Capital Expenditure within the Water category. The matter had an initial "
        "filing on April 7, 2025 and a final filing on October 23, 2025."
    ) in reply.text
    assert "I found 13 Exhibits, 5 Key Documents, 21 Other Documents, and no Transcripts or Recordings" in reply.text
    assert "I downloaded 10 out of the 21 Other Documents" in reply.text
    assert "and am attaching them as a ZIP here." in reply.text


def test_counts_include_a_grand_total(counts):
    assert counts_sentence(counts).endswith("(39 files in total).")


def test_counts_singular_and_all_present():
    counts = {t: 1 for t in DocType}
    assert counts_sentence(counts) == (
        "I found 1 Exhibit, 1 Key Document, 1 Other Document, 1 Transcript, and 1 Recording (5 files in total)."
    )


def test_counts_all_zero():
    counts = {t: 0 for t in DocType}
    assert counts_sentence(counts) == (
        "I found no Exhibits, Key Documents, Other Documents, Transcripts, or Recordings in this matter."
    )


def test_zero_documents_of_requested_type(metadata, counts):
    result = make_result(metadata, counts, [], doc_type=DocType.TRANSCRIPTS)
    assert download_sentence(result, attaching_here=False) == (
        "There are no Transcripts in this matter, so there is nothing to download."
    )


def test_all_documents_downloaded(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 5), doc_type=DocType.KEY_DOCUMENTS)
    assert download_sentence(result, attaching_here=False) == "I downloaded all 5 Key Documents."


def test_partial_failures_are_reported(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 4), doc_type=DocType.KEY_DOCUMENTS)
    result.failures.append("97289: could not download (ScrapeError)")
    text = download_sentence(result, attaching_here=False)
    assert "I downloaded 4 out of the 5 Key Documents" in text
    assert "I couldn't download 1 of them: 97289" in text


def test_start_position_is_described(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 3), start=4, limit=3)
    assert "(numbers 4 to 6 as listed on the UARB site)" in download_sentence(result, attaching_here=False)


def test_recordings_budget_explains_how_to_get_more(tmp_path, metadata):
    counts = {t: 0 for t in DocType} | {DocType.RECORDINGS: 23}
    result = make_result(metadata, counts, make_files(tmp_path, 3, size=300_000_000), doc_type=DocType.RECORDINGS)
    result.skipped_for_size = 7
    text = download_sentence(result, attaching_here=False)
    assert "I stopped after 3 (900.0 MB)" in text
    assert '"send recordings 4-6 for M12205"' in text


def test_link_only_for_large_zips(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 10))
    reply = compose_result(ReplyParts(results=[result], delivery=Delivery.LINK_ONLY, zip_size=124_000_000,
                                      link="https://x/y.zip", job_id="j"))
    assert "and am attaching" not in reply.text
    assert "The ZIP is 124.0 MB, which is too large to attach" in reply.text
    assert '<a href="https://x/y.zip"' in reply.html
    assert "Too large to attach to an email" in reply.html


def test_html_escapes_document_titles(tmp_path, metadata, counts):
    files = make_files(tmp_path, 1)
    files[0].row.title = "<script>alert(1)</script>"
    reply = compose_result(ReplyParts(results=[make_result(metadata, counts, files)], job_id="j"))
    assert "<script>" not in reply.html


def test_multi_request_mentions_matter_once(tmp_path, metadata, counts):
    a = make_result(metadata, counts, make_files(tmp_path, 2))
    b = make_result(metadata, counts, [], doc_type=DocType.TRANSCRIPTS)
    reply = compose_result(ReplyParts(results=[a, b], delivery=Delivery.INLINE, zip_size=2000,
                                      link="https://x/y.zip", job_id="j"))
    assert reply.text.count("M12205 is about") == 1
    assert "All the files are attached in one ZIP" in reply.text


def test_ack_warns_that_recordings_are_slow():
    reply = compose_ack([DocRequest(matter="M10431", doc_type=DocType.RECORDINGS)], "j")
    assert "10-15 minutes" in reply.text


def test_fmt_size():
    assert fmt_size(450_576) == "0.5 MB"
    assert fmt_size(37_977) == "37 KB"


def test_status_badge(tmp_path, metadata, counts):
    ok = make_result(metadata, counts, make_files(tmp_path, 2))
    assert "Ready" in compose_result(ReplyParts(results=[ok], job_id="j")).html
    ok.failures.append("1: could not download (ScrapeError)")
    assert "Partially ready" in compose_result(ReplyParts(results=[ok], job_id="j")).html
    empty = make_result(metadata, counts, [], doc_type=DocType.TRANSCRIPTS)
    assert "No files" in compose_result(ReplyParts(results=[empty], job_id="j")).html


def test_errors_only_reply(tmp_path):
    reply = compose_result(ReplyParts(results=[], errors=[Notice("I couldn't find matter M99999", "Check it.")],
                                      job_id="j"))
    assert reply.text.startswith("Hi there,\n\nI couldn't find matter M99999")
    assert "find matter M99999" in reply.html


def test_link_expiry_is_shown(tmp_path, metadata, counts):
    result = make_result(metadata, counts, make_files(tmp_path, 1))
    reply = compose_result(ReplyParts(results=[result], delivery=Delivery.INLINE, zip_size=1000,
                                      link="https://x/y.zip", link_expires=date(2026, 11, 4), job_id="j"))
    assert "link expires Nov 4, 2026" in reply.html
    assert "until November 4, 2026" in reply.text


@pytest.mark.parametrize("header,expected", [
    ("Nona Yorbiznes <x@protonmail.com>", "Nona"),
    ('"jane doe" <jane@example.com>', "Jane"),
    ("Mary-Kate O'Neil <m@example.com>", "Mary-Kate"),
    ("jane@example.com", "there"),
    ("<jane@example.com>", "there"),
    ("Team 42 <t@example.com>", "Team"),
    ("1234 <t@example.com>", "there"),
    ("", "there"),
])
def test_first_name(header, expected):
    assert first_name(header) == expected


def test_greeting_in_every_email(tmp_path, metadata, counts):
    result = compose_result(ReplyParts(results=[make_result(metadata, counts, [])], job_id="j", name="Nona"))
    ack = compose_ack([DocRequest(matter="M12205", doc_type=DocType.EXHIBITS)], "j", "Nona")
    for reply in (result, ack):
        assert reply.text.startswith("Hi Nona,")
        assert "Hi Nona," in reply.html
