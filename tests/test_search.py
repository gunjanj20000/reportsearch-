"""Automated unit and integration tests for FTS5 Search Engine, BM25, and Synonyms."""

import tempfile
import time
from pathlib import Path
import pytest

from indexer.database.connection import DatabaseManager
from indexer.search.query_parser import FTS5QueryParser
from indexer.search.synonyms import SynonymManager
from indexer.search.suggestions import SuggestionService
from indexer.search.search_service import SearchService
from indexer.models import ExtractedDocument, ExtractedPage, ExtractedParagraph, ExtractionStatus


@pytest.fixture
def populated_search_service():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "search_test.db"
        db = DatabaseManager(db_path)

        # Seed sample documents
        doc1 = ExtractedDocument(
            filename="Left_Main_Revasc.pdf",
            extension=".pdf",
            file_size=100000,
            modified_time=1700000000.0,
            sha256="hash1",
            source_path="/docs/Left_Main_Revasc.pdf",
            title="Left Main Coronary Artery Revascularization",
            page_count=3,
            pages=[
                ExtractedPage(page_number=1, text="Left Main (LM) lesions treated with IVUS guidance."),
                ExtractedPage(page_number=2, text="Chronic Total Occlusion (CTO) crossing with retrograde wire."),
                ExtractedPage(page_number=3, text="Excimer Laser Coronary Atherectomy (ELCA) in calcified plaques.")
            ],
            paragraphs=[
                ExtractedParagraph(page_number=1, paragraph_number=1, text="Left Main (LM) lesions treated with IVUS guidance."),
                ExtractedParagraph(page_number=2, paragraph_number=2, text="Chronic Total Occlusion (CTO) crossing with retrograde wire."),
                ExtractedParagraph(page_number=3, paragraph_number=3, text="Excimer Laser Coronary Atherectomy (ELCA) in calcified plaques.")
            ]
        )
        db.save_document(doc1)

        doc2 = ExtractedDocument(
            filename="Stent_Thrombosis_Trial.docx",
            extension=".docx",
            file_size=50000,
            modified_time=1700000000.0,
            sha256="hash2",
            source_path="/docs/Stent_Thrombosis_Trial.docx",
            title="Drug-Eluting Stent Outcomes and Thrombosis",
            page_count=1,
            pages=[ExtractedPage(page_number=1, text="Stent expansion prevents acute stent thrombosis.")],
            paragraphs=[
                ExtractedParagraph(page_number=1, paragraph_number=1, text="Stent expansion prevents acute stent thrombosis."),
                ExtractedParagraph(page_number=1, paragraph_number=2, text="Lithotripsy was utilized for calcification.")
            ]
        )
        db.save_document(doc2)

        service = db.get_search_service()
        yield service
        db.close()


def test_query_parser_phrase_and_boolean():
    parser = FTS5QueryParser()

    # Exact phrase
    assert parser.parse('"left main"') == '"left main"'

    # Implicit AND
    assert parser.parse('ivus cto') == 'ivus AND cto'

    # Explicit AND / OR
    assert parser.parse('ivus OR oct') == 'ivus OR oct'
    assert parser.parse('ivus AND oct') == 'ivus AND oct'

    # Exclusion
    assert parser.parse('stent -thrombosis') == 'stent NOT thrombosis'
    assert parser.parse('stent NOT thrombosis') == 'stent NOT thrombosis'

    # Prefix search
    assert parser.parse('litho*') == 'litho*'

    # Unclosed double quote
    assert parser.parse('"left main') == '"left main"'


def test_synonym_expansion():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "syn_test.db")
        syn_mgr = db.get_search_service().synonym_manager

        # Test single acronym expansion
        expanded, used = syn_mgr.expand_query("LM")
        assert len(used) == 1
        assert used[0] == ("LM", "Left Main")
        assert '("LM" OR "Left Main")' in expanded

        # Test expansion preserves original query in tuple
        expanded, used = syn_mgr.expand_query("CTO intervention")
        assert any(t[0] == "CTO" for t in used)

        # Test multi-word expansion (Left Main -> LM)
        expanded, used = syn_mgr.expand_query("Left Main stent")
        assert any(t[0] == "Left Main" for t in used)

        db.close()


def test_synonym_crud_operations():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(Path(tmp_dir) / "syn_crud.db")
        syn_mgr = db.get_search_service().synonym_manager

        initial_count = len(syn_mgr.get_all())
        syn_id = syn_mgr.add("TEST_ACR", "Test Acronym Expansion")
        assert syn_id > 0
        assert len(syn_mgr.get_all()) == initial_count + 1

        # Test expansion of newly added synonym
        exp, used = syn_mgr.expand_query("TEST_ACR")
        assert len(used) == 1
        assert used[0][1] == "Test Acronym Expansion"

        # Update
        syn_mgr.update(syn_id, "TEST_ACR", "Updated Acronym Expansion", enabled=True)
        exp, used = syn_mgr.expand_query("TEST_ACR")
        assert used[0][1] == "Updated Acronym Expansion"

        # Delete
        syn_mgr.delete(syn_id)
        assert len(syn_mgr.get_all()) == initial_count

        db.close()


def test_search_execution_and_bm25(populated_search_service):
    # Phrase search
    res = populated_search_service.search('"Left Main"')
    assert res.total_count >= 1
    assert any("Left Main" in item.title or "Left Main" in item.snippet for item in res.items)
    assert res.execution_time_ms < 50.0  # Must be fast

    # Boolean search
    res_bool = populated_search_service.search('IVUS AND lesions')
    assert res_bool.total_count >= 1

    # Exclusion search
    res_excl = populated_search_service.search('stent -thrombosis')
    # doc2 contains both "stent" and "thrombosis", so paragraphs mentioning thrombosis should not match
    for item in res_excl.items:
        assert "thrombosis" not in item.snippet.lower()


def test_search_with_synonyms_enabled(populated_search_service):
    # Query with acronym LM, should find "Left Main"
    res = populated_search_service.search("LM", expand_synonyms=True)
    assert res.total_count >= 1
    assert res.expanded_query is not None
    assert len(res.synonyms_applied) > 0
    assert any(t[0] == "LM" for t in res.synonyms_applied)


def test_search_filters_and_pagination(populated_search_service):
    # Filter by PDF extension only
    res_pdf = populated_search_service.search("calcified", extensions=[".pdf"])
    assert res_pdf.total_count >= 1
    assert all(item.extension == ".pdf" for item in res_pdf.items)

    # Filter by DOCX extension only
    res_docx = populated_search_service.search("calcification", extensions=[".docx"])
    assert res_docx.total_count >= 1
    assert all(item.extension == ".docx" for item in res_docx.items)

    # Pagination test
    res_page = populated_search_service.search("stent OR IVUS", page=1, page_size=1)
    assert len(res_page.items) == 1
    assert res_page.page == 1
    assert res_page.page_size == 1
    assert res_page.total_pages >= 2


def test_suggestions_service(populated_search_service):
    suggestions = populated_search_service.get_suggestions("retro")
    assert len(suggestions) >= 1
    assert any(s["text"] == "retrograde" for s in suggestions)

    # Synonym suggestion
    syn_sug = populated_search_service.get_suggestions("oct")
    assert any(s["type"] == "synonym" for s in syn_sug)


def test_search_performance_benchmark(populated_search_service):
    """Verify search latency target < 50ms for typical queries."""
    benchmark_queries = [
        "IVUS",
        '"Chronic Total Occlusion"',
        "ELCA OR IVL",
        "stent -thrombosis",
        "retrograde",
        "plaque*"
    ]
    latencies = []
    for q in benchmark_queries:
        t0 = time.perf_counter()
        res = populated_search_service.search(q)
        lat = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat)
        assert lat < 100.0, f"Query '{q}' took {lat:.2f}ms which exceeds 100ms"

    avg_latency = sum(latencies) / len(latencies)
    assert avg_latency < 50.0, f"Average latency {avg_latency:.2f}ms exceeds 50ms"
