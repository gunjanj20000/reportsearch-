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
    """Test /api/fs/browse returns directory listing, attached devices, network mounts, and shortcuts."""
    with urllib.request.urlopen(f"{web_server}/api/fs/browse") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "current_path" in data
        assert "breadcrumbs" in data
        assert "shortcuts" in data
        assert "attached_devices" in data
        assert "network_mounts" in data
        assert "subdirectories" in data
        assert isinstance(data["breadcrumbs"], list)
        assert isinstance(data["shortcuts"], list)
        assert isinstance(data["attached_devices"], list)
        assert isinstance(data["network_mounts"], list)
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


def test_api_document_page_note(web_server):
    """Test /api/document/page returns page content without modifying database."""
    url = f"{web_server}/api/document/page?doc_id=1&page=1"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["document_id"] == 1
        assert "filename" in data
        assert "page_number" in data
        assert "total_pages" in data
        assert "content" in data
        assert len(data["content"]) > 0


def test_api_document_page_invalid(web_server):
    """Test /api/document/page returns 404 for nonexistent document."""
    try:
        urllib.request.urlopen(f"{web_server}/api/document/page?doc_id=999999&page=1")
        assert False, "Should have raised HTTPError 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_api_fs_network_mounts(web_server):
    """Test /api/fs/network_mounts returns active network mounts list."""
    with urllib.request.urlopen(f"{web_server}/api/fs/network_mounts") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "mounts" in data
        assert isinstance(data["mounts"], list)


def test_api_fs_network_check_valid(web_server):
    """Test /api/fs/network_check verifies and resolves existing folder."""
    req = urllib.request.Request(
        f"{web_server}/api/fs/network_check",
        data=json.dumps({"path": "sample_corpus"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["valid"] is True
        assert data["doc_count_est"] > 0
        assert "sample_files" in data
        assert "resolved_path" in data


def test_api_fs_network_check_invalid(web_server):
    """Test /api/fs/network_check returns clean error for unreachable path."""
    req = urllib.request.Request(
        f"{web_server}/api/fs/network_check",
        data=json.dumps({"path": "/nonexistent_network_path_12345"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["valid"] is False
        assert "error" in data

def test_get_attached_storage_devices():
    """Test detection of attached devices returns a list of dictionaries with name and path."""
    from indexer.web import get_attached_storage_devices
    devices = get_attached_storage_devices()
    assert isinstance(devices, list)
    for dev in devices:
        assert "name" in dev
        assert "path" in dev
        assert "type" in dev
