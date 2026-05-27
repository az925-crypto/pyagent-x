import sys
import types
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(scope="module")
def server_app():
    # Set up mocks in sys.modules before importing server
    mock_scan = types.ModuleType("tools.scan")
    mock_scan.resolve_dns = AsyncMock()
    mock_scan.resolve_mx = AsyncMock()
    mock_scan.scan_target = AsyncMock()

    mock_orch = types.ModuleType("tools.orchestrator")
    mock_orch.run_ig = AsyncMock()
    mock_orch.run_sherlock = AsyncMock()
    mock_orch.run_scan = AsyncMock()

    mocks = {
        "instagrapi": MagicMock(),
        "tools.ig": MagicMock(),
        "tools.ig.profile": MagicMock(),
        "tools.ig.followers": MagicMock(),
        "tools.ig.following": MagicMock(),
        "tools.ig.media": MagicMock(),
        "tools.ig.download": MagicMock(),
        "tools.scan": mock_scan,
        "tools.sherlock": MagicMock(),
        "tools.orchestrator": mock_orch,
    }

    for name, mod in mocks.items():
        sys.modules[name] = mod

    from server import app
    app.config["TESTING"] = True

    # Clear rate limiter for clean test
    import server as srv
    srv._rate_limit_store.clear()

    yield app

    # Clean up to avoid polluting other tests
    for name in mocks:
        if name in sys.modules:
            del sys.modules[name]


@pytest.fixture
def client(server_app):
    with server_app.test_client() as c:
        yield c


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_api_status_no_key(client):
    with patch.dict("os.environ", {}, clear=True):
        resp = client.get("/api/status")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get("aiStatus") == "NOT_CONFIGURED"


def test_api_status_with_key_but_no_ai(client):
    env = {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}
    with patch.dict("os.environ", env, clear=True):
        resp = client.get("/api/status")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get("aiStatus") == "ERROR"


def test_api_status_connected(client):
    env = {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}
    mock_ai = MagicMock()
    mock_ai.generate_content = AsyncMock(
        return_value=MagicMock(text="pong")
    )
    with patch.dict("os.environ", env, clear=True):
        with patch("server.get_ai", return_value=mock_ai):
            resp = client.get("/api/status")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data.get("aiStatus") == "CONNECTED"


def test_osint_scan_missing_target(client):
    resp = client.post("/api/osint/scan", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


def test_osint_scan_invalid_target(client):
    resp = client.post("/api/osint/scan", json={"target": {"type": "INVALID", "value": "x"}})
    assert resp.status_code == 400


def test_osint_scan_no_ai(client):
    resp = client.post("/api/osint/scan", json={
        "target": {"type": "IP", "value": "8.8.8.8"},
    })
    assert resp.status_code == 500
    data = resp.get_json()
    assert "error" in data


def test_reload_provider(client):
    with patch("server.recreate_provider", return_value=MagicMock()):
        with patch("server.get_provider_info", return_value={"type": "gemini", "model": "test"}):
            resp = client.post("/api/admin/reload-provider")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_reload_provider_fails(client):
    with patch("server.recreate_provider", side_effect=ValueError("bad key")):
        resp = client.post("/api/admin/reload-provider")
    assert resp.status_code == 500
    data = resp.get_json()
    assert "error" in data


def test_rate_limit_exceeded(client):
    with patch("server._rate_limit_store", {}):
        with patch("server.RATE_LIMIT_MAX", 1):
            with patch("server.recreate_provider", return_value=MagicMock()):
                with patch("server.get_provider_info", return_value={"type": "gemini", "model": "test"}):
                    resp = client.post("/api/admin/reload-provider")
                    assert resp.status_code == 200
                    resp = client.post("/api/admin/reload-provider")
                    assert resp.status_code == 429


def test_forbidden_origin(client):
    resp = client.post("/api/osint/scan", json={
        "target": {"type": "IP", "value": "8.8.8.8"},
    }, headers={"Origin": "http://evil.com"})
    assert resp.status_code == 403
