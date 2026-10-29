import pytest

from uarb_agent.intent import IntentParser
from uarb_agent.models import DocType


@pytest.fixture
def parser() -> IntentParser:
    return IntentParser(api_key="test", model="test", base_url="http://localhost", max_requests=3)


def req(matter="M12205", doc_type="Other Documents", **kw):
    return {"matter": matter, "doc_type": doc_type, **kw}


def test_valid_request(parser):
    parsed = parser._validate({"requests": [req(limit=5)], "clarification_needed": None})
    assert [(r.matter, r.doc_type, r.limit) for r in parsed.requests] == [("M12205", DocType.OTHER_DOCUMENTS, 5)]


def test_matter_is_normalized(parser):
    assert parser._validate({"requests": [req(matter="12205")]}).requests[0].matter == "M12205"
    assert parser._validate({"requests": [req(matter="m12205")]}).requests[0].matter == "M12205"


def test_more_than_ten_is_capped_with_a_note(parser):
    parsed = parser._validate({"requests": [req(limit=50)]})
    assert parsed.requests[0].limit == 10
    assert "at most 10" in parsed.notes[0]


def test_extra_requests_are_dropped_with_a_note(parser):
    types = ["Exhibits", "Key Documents", "Other Documents", "Transcripts"]
    parsed = parser._validate({"requests": [req(doc_type=t) for t in types]})
    assert len(parsed.requests) == 3
    assert "Transcripts for M12205" in parsed.notes[0]


def test_duplicates_are_merged(parser):
    assert len(parser._validate({"requests": [req(), req()]}).requests) == 1


def test_invalid_matter_asks_for_clarification(parser):
    parsed = parser._validate({"requests": [req(matter="M123")]})
    assert parsed.requests == []
    assert "matter number" in parsed.clarification_needed


def test_invented_doc_type_asks_for_clarification(parser):
    parsed = parser._validate({"requests": [req(doc_type="Secret Files")]})
    assert parsed.requests == [] and parsed.clarification_needed


def test_clarification_passes_through(parser):
    parsed = parser._validate({"requests": [], "clarification_needed": "Which type?"})
    assert parsed.clarification_needed == "Which type?"


def test_empty_output_is_an_error(parser):
    with pytest.raises(ValueError):
        parser._validate({"requests": [], "clarification_needed": None})
