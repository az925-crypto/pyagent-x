import pytest
from utils import validate_target, is_valid_ip


class TestValidateTarget:
    def test_valid_uppercase(self):
        assert validate_target({"type": "DOMAIN", "value": "example.com"}) is True
        assert validate_target({"type": "IP", "value": "8.8.8.8"}) is True
        assert validate_target({"type": "EMAIL", "value": "user@example.com"}) is True
        assert validate_target({"type": "USERNAME", "value": "johndoe"}) is True

    def test_valid_lowercase(self):
        assert validate_target({"type": "domain", "value": "example.com"}) is True
        assert validate_target({"type": "ip", "value": "8.8.8.8"}) is True
        assert validate_target({"type": "email", "value": "user@example.com"}) is True
        assert validate_target({"type": "username", "value": "johndoe"}) is True

    def test_invalid_type(self):
        assert validate_target({"type": "INVALID", "value": "test"}) is False

    def test_invalid_targets(self):
        assert validate_target(None) is False
        assert validate_target({}) is False
        assert validate_target({"type": "DOMAIN"}) is False
        assert validate_target({"value": "example.com"}) is False
        assert validate_target({"type": "DOMAIN", "value": ""}) is False
        assert validate_target({"type": "DOMAIN", "value": "   "}) is False


class TestIsValidIP:
    def test_valid_ips(self):
        assert is_valid_ip("8.8.8.8") is True
        assert is_valid_ip("192.168.1.1") is True
        assert is_valid_ip("0.0.0.0") is True
        assert is_valid_ip("255.255.255.255") is True

    def test_invalid_ips(self):
        assert is_valid_ip("999.999.999.999") is False
        assert is_valid_ip("256.1.2.3") is False
        assert is_valid_ip("") is False
        assert is_valid_ip("not-an-ip") is False
        assert is_valid_ip("1.2.3") is False
        assert is_valid_ip("1.2.3.4.5") is False


class TestResolveTargetData:
    @pytest.mark.asyncio
    async def test_domain_uppercase(self):
        async def dns_mock(d): return ["1.2.3.4"]
        async def mx_mock(d): return []
        async def geo_mock(ip): return {"city": "Mock City", "country": "Mock Country"}
        from utils import resolve_target_data
        ips, geo = await resolve_target_data("DOMAIN", "example.com", dns_mock, mx_mock, geo_mock)
        assert ips == ["1.2.3.4"]
        assert geo["city"] == "Mock City"

    @pytest.mark.asyncio
    async def test_domain_lowercase(self):
        async def dns_mock(d): return ["1.2.3.4"]
        async def mx_mock(d): return []
        async def geo_mock(ip): return {"city": "Mock City", "country": "Mock Country"}
        from utils import resolve_target_data
        ips, geo = await resolve_target_data("domain", "example.com", dns_mock, mx_mock, geo_mock)
        assert ips == ["1.2.3.4"]
        assert geo["city"] == "Mock City"

    @pytest.mark.asyncio
    async def test_ip(self):
        async def dns_mock(d): return []
        async def mx_mock(d): return []
        async def geo_mock(ip): return {"city": "Mock City", "country": "Mock Country"}
        from utils import resolve_target_data
        ips, geo = await resolve_target_data("IP", "8.8.8.8", dns_mock, mx_mock, geo_mock)
        assert ips == ["8.8.8.8"]
        assert geo["city"] == "Mock City"

    @pytest.mark.asyncio
    async def test_email(self):
        async def dns_mock(d): return []
        async def mx_mock(d): return ["mx.example.com"]
        async def geo_mock(ip): return {}
        from utils import resolve_target_data
        ips, geo = await resolve_target_data("EMAIL", "user@example.com", dns_mock, mx_mock, geo_mock)
        assert ips == ["mx.example.com"]
        assert geo == {}

    @pytest.mark.asyncio
    async def test_username(self):
        async def dns_mock(d): return []
        async def mx_mock(d): return []
        async def geo_mock(ip): return {}
        from utils import resolve_target_data
        ips, geo = await resolve_target_data("USERNAME", "johndoe", dns_mock, mx_mock, geo_mock)
        assert ips == []
        assert geo == {}
