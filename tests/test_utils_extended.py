import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock
from utils import fetch_geoip, check_reddit, check_github


class MockAsyncClient:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def set_get_response(self, response):
        self._get_response = response
        self.get = AsyncMock(return_value=response)

    def set_get_side_effect(self, side_effect):
        self.get = AsyncMock(side_effect=side_effect)


class TestFetchGeoIP:
    @pytest.mark.asyncio
    async def test_geojs_success(self):
        mock_response = AsyncMock()
        mock_response.is_success = True
        mock_response.json = MagicMock(return_value={"ip": "8.8.8.8", "city": "Mountain View", "country": "US"})

        mock_client = MockAsyncClient()
        mock_client.set_get_response(mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_geoip("8.8.8.8")

        assert result["ip"] == "8.8.8.8"
        assert result["city"] == "Mountain View"
        assert result["country"] == "US"

    @pytest.mark.asyncio
    async def test_geojs_fails_fallback_ipapi(self):
        ipapi_resp = AsyncMock()
        ipapi_resp.is_success = True
        ipapi_resp.json = MagicMock(return_value={
            "status": "success", "query": "8.8.8.8",
            "city": "Ashburn", "country": "US",
            "org": "AS15169 Google LLC", "as": "AS15169",
        })

        async def get_side_effect(url, **kwargs):
            if "geojs" in url:
                raise Exception("GeoJS network error")
            return ipapi_resp

        mock_client = MockAsyncClient()
        mock_client.set_get_side_effect(get_side_effect)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_geoip("8.8.8.8")

        assert result["city"] == "Ashburn"
        assert result["organization_name"] == "AS15169 Google LLC"
        assert result["asn"] == "AS15169"

    @pytest.mark.asyncio
    async def test_both_fail_return_empty(self):
        mock_client = MockAsyncClient()
        mock_client.set_get_side_effect(Exception("Network error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_geoip("8.8.8.8")

        assert result == {}

    @pytest.mark.asyncio
    async def test_ipapi_non_success(self):
        fail_resp = AsyncMock()
        fail_resp.is_success = True
        fail_resp.json = MagicMock(return_value={"status": "fail", "message": "invalid query"})

        async def get_side_effect(url, **kwargs):
            if "geojs" in url:
                raise Exception("GeoJS error")
            return fail_resp

        mock_client = MockAsyncClient()
        mock_client.set_get_side_effect(get_side_effect)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_geoip("invalid")

        assert result == {}


class TestCheckReddit:
    @pytest.mark.asyncio
    async def test_user_exists(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await check_reddit("testuser")

        assert result is True

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        mock_response = AsyncMock()
        mock_response.status_code = 404

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await check_reddit("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch.object(httpx.AsyncClient, "get", side_effect=Exception("Network error")):
            result = await check_reddit("testuser")

        assert result is False


class TestCheckGitHub:
    @pytest.mark.asyncio
    async def test_user_exists(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await check_github("testuser")

        assert result is True

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        mock_response = AsyncMock()
        mock_response.status_code = 404

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await check_github("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch.object(httpx.AsyncClient, "get", side_effect=Exception("Network error")):
            result = await check_github("testuser")

        assert result is False

    @pytest.mark.asyncio
    async def test_sends_auth_header_with_token(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch.object(httpx.AsyncClient, "get", return_value=mock_response) as mock_get, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}):
            result = await check_github("testuser")

        assert result is True
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer ghp_test123"
