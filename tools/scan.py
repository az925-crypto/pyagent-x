import time
import asyncio
import socket
from utils import is_valid_ip, fetch_geoip


async def resolve_dns(domain: str) -> list[str]:
    try:
        info = await asyncio.to_thread(socket.getaddrinfo, domain, 80)
        ips = list(set(i[4][0] for i in info))
        return ips
    except Exception:
        return []


async def resolve_mx(domain: str) -> list[str]:
    try:
        import dns.resolver
        records = await asyncio.to_thread(dns.resolver.resolve, domain, "MX")
        return [str(r.exchange) for r in records]
    except ImportError:
        try:
            _, _, ips = await asyncio.to_thread(socket.gethostbyname_ex, domain)
            return ips
        except Exception:
            return []
    except Exception:
        return []


async def scan_target(target: str) -> dict:
    start = time.monotonic()
    source = "scan/py"

    try:
        ip_to_scan = target
        dns_records = []

        if not is_valid_ip(target):
            try:
                records = await resolve_dns(target)
                dns_records = records
                ip_to_scan = records[0] if records else ""
            except Exception:
                ip_to_scan = ""
        else:
            dns_records = [target]

        geo_data = {}
        if ip_to_scan:
            geo_data = await fetch_geoip(ip_to_scan)

        return {
            "success": True,
            "data": {"target": target, "resolvedIPs": dns_records, "geoData": geo_data},
            "meta": {"source": source, "duration_ms": int((time.monotonic() - start) * 1000)},
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "meta": {"source": source, "duration_ms": int((time.monotonic() - start) * 1000)},
        }
