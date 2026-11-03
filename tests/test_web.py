"""Tests for indexer.web zero-dependency HTTP server and REST endpoints."""

import json
import threading
import time
import urllib.request
import pytest
from pathlib import Path
from http.server import ThreadingHTTPServer

from indexer.web import MedicalSearchHandler, WebState, _state
from indexer.config import DEFAULT_DB_PATH
import indexer.web as web_module


@pytest.fixture(scope="module")
def web_server():
    """Start web server on an ephemeral port in a daemon thread."""
    web_module._state = WebState(DEFAULT_DB_PATH)
    server = ThreadingHTTPServer(("127.0.0.1", 0), MedicalSearchHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()


def test_web_index_html(web_server):
    """Test that the root URL returns the SPA HTML document."""
    with urllib.request.urlopen(f"{web_server}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type")
        html = resp.read().decode("utf-8")
        assert "Medical Literature Search" in html
        assert "mTotalDocs" in html


def test_api_stats(web_server):
    """Test /api/stats returns valid dashboard metrics."""
    with urllib.request.urlopen(f"{web_server}/api/stats") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "total_documents" in data
        assert "total_original_file_size" in data
        assert "database_size" in data
        assert data["total_documents"] >= 0


def test_api_search_and_synonyms(web_server):
    """Test /api/search returns results and expands cardiology synonyms."""
    # Query with synonym
    url = f"{web_server}/api/search?q=LM&synonyms=true"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "results" in data
        assert "total_count" in data
        assert "parsed_query" in data
        assert data["total_count"] >= 0


def test_api_suggestions(web_server):
    """Test /api/suggest returns typeahead completions."""
    url = f"{web_server}/api/suggest?q=stent"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)


def test_api_synonyms_list(web_server):
    """Test /api/synonyms returns active cardiology abbreviations."""
    with urllib.request.urlopen(f"{web_server}/api/synonyms") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "synonyms" in data
        assert len(data["synonyms"]) > 0


def test_api_export_preview(web_server):
    """Test /api/export/preview returns sizing estimates."""
    with urllib.request.urlopen(f"{web_server}/api/export/preview") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "actual_db_size" in data
        assert "estimated_zstd_size" in data


def test_api_fs_browse(web_server):
    """Test /api/fs/browse returns directory listing and shortcuts."""
    with urllib.request.urlopen(f"{web_server}/api/fs/browse") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "current_path" in data
        assert "breadcrumbs" in data
        assert "shortcuts" in data
        assert "subdirectories" in data
        assert isinstance(data["breadcrumbs"], list)
        assert isinstance(data["shortcuts"], list)
        assert isinstance(data["subdirectories"], list)


def test_api_fs_native_dialog(web_server):
    """Test /api/fs/native_dialog responds with supported status."""
    req = urllib.request.Request(
        f"{web_server}/api/fs/native_dialog",
        data=json.dumps({"initial_dir": ""}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "supported" in data
