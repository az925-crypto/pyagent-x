import re
import os
import httpx

GEO_USER_AGENT = "OSINT-Agent-X/1.0"
VALID_TYPES = ["IP", "DOMAIN", "USERNAME", "EMAIL", "ip", "domain", "username", "email"]
IP_REGEX = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def validate_target(target: dict) -> bool:
    if not isinstance(target, dict):
        return False
    if not isinstance(target.get("value"), str) or not isinstance(target.get("type"), str):
        return False
    if target["value"].strip() == "":
        return False
    if target["type"] not in VALID_TYPES:
        return False
    return True


def is_valid_ip(ip: str) -> bool:
    match = IP_REGEX.match(ip)
    if not match:
        return False
    return all(int(octet) <= 255 for octet in match.groups())


async def fetch_geoip(ip: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"https://get.geojs.io/v1/ip/geo/{ip}.json",
                headers={"User-Agent": GEO_USER_AGENT},
            )
            if res.is_success:
                data = res.json()
                if data.get("ip"):
                    return data
    except Exception as e:
        print(f"[GeoIP] Primary failed: {e}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,message,country,city,org,as,query",
                headers={"User-Agent": GEO_USER_AGENT},
            )
            if res.is_success:
                data = res.json()
                if data.get("status") == "success":
                    return {
                        "ip": data["query"],
                        "city": data.get("city", ""),
                        "country": data.get("country", ""),
                        "organization_name": data.get("org", ""),
                        "organization": data.get("org", ""),
                        "asn": data.get("as", ""),
                    }
    except Exception as e:
        print(f"[GeoIP] Fallback failed: {e}")
    return {}


async def check_reddit(username: str, signal: httpx.Timeout | None = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"https://old.reddit.com/user/{username}/about.json",
                headers={"User-Agent": f"{GEO_USER_AGENT} (by /u/agent_x)"},
            )
            return res.status_code == 200
    except Exception:
        return False


async def check_github(username: str, signal: httpx.Timeout | None = None) -> bool:
    headers = {"User-Agent": GEO_USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"https://api.github.com/users/{username}", headers=headers
            )
            return res.status_code == 200
    except Exception:
        return False


async def resolve_target_data(
    target_type: str,
    target_value: str,
    dns_resolver,
    mx_resolver,
    geo_fetcher,
) -> tuple[list[str], dict]:
    resolved_ips: list[str] = []
    geo_data: dict = {}
    ip_to_scan = target_value
    t = target_type.upper()

    if t == "EMAIL":
        parts = target_value.split("@")
        if len(parts) == 2:
            ip_to_scan = parts[1]
    elif t == "USERNAME":
        ip_to_scan = ""

    if ip_to_scan and not is_valid_ip(ip_to_scan):
        try:
            if t == "EMAIL":
                resolved_ips = await mx_resolver(ip_to_scan)
            else:
                resolved_ips = await dns_resolver(ip_to_scan)
                ip_to_scan = resolved_ips[0] if resolved_ips else ""
        except Exception as e:
            print(f"[DNS] Resolution failed for {ip_to_scan}: {e}")
            ip_to_scan = ""
    elif ip_to_scan:
        resolved_ips = [ip_to_scan]

    if ip_to_scan and t not in ("EMAIL", "USERNAME"):
        try:
            geo_data = await geo_fetcher(ip_to_scan)
        except Exception as e:
            print(f"[GeoIP] Lookup failed for {ip_to_scan}: {e}")

    return resolved_ips, geo_data
