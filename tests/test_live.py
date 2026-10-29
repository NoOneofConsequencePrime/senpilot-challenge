"""Hits the real UARB site. Run with `pytest -m live`; excluded from CI."""

import pytest

from uarb_agent.models import DocRequest, DocType
from uarb_agent.scraper import MatterNotFound, UarbScraper

pytestmark = pytest.mark.live


def test_key_documents_for_the_example_matter(tmp_path):
    result = UarbScraper(1024**3).fetch(DocRequest(matter="M12205", doc_type=DocType.KEY_DOCUMENTS, limit=2), tmp_path)
    assert result.metadata.title.startswith("Halifax Regional Water Commission")
    assert result.metadata.type == "Water"
    assert all(result.counts[t] >= 0 for t in DocType) and result.counts[DocType.EXHIBITS] >= 13
    assert len(result.files) == 2
    assert all(f.path.read_bytes()[:4] == b"%PDF" for f in result.files)


def test_unknown_matter(tmp_path):
    with pytest.raises(MatterNotFound):
        UarbScraper(1024**3).fetch(DocRequest(matter="M99999", doc_type=DocType.EXHIBITS), tmp_path)
