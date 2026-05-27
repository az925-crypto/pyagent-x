import time
import httpx
from utils import check_reddit, check_github


async def _check_gitlab(username: str, _signal=None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://gitlab.com/api/v4/users?username={username}")
            if res.status_code == 200:
                data = res.json()
                return isinstance(data, list) and len(data) > 0 and data[0].get("username") == username
            return False
    except Exception:
        return False


async def _check_tiktok(username: str, _signal=None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.get(f"https://www.tiktok.com/@{username}")
            text = res.text
            return res.status_code == 200 and "This page could not be found" not in text and f"@{username}" in text
    except Exception:
        return False


async def _check_medium(username: str, _signal=None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://medium.com/@{username}")
            text = res.text
            return res.status_code == 200 and "Page Not Found" not in text and f"@{username}" in text
    except Exception:
        return False


async def _check_vimeo(username: str, _signal=None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://vimeo.com/{username}")
            text = res.text
            return res.status_code == 200 and "Page Not Found" not in text and "/search" not in str(res.url)
    except Exception:
        return False


async def _check_vk(username: str, _signal=None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://vk.com/{username}")
            return res.status_code == 200
    except Exception:
        return False


PLATFORMS = [
    {"name": "GitHub", "label": "KONFIRMASI AKTIF", "check": check_github},
    {"name": "GitLab", "label": "KONFIRMASI AKTIF", "check": _check_gitlab},
    {"name": "Reddit", "label": "KONFIRMASI AKTIF", "check": check_reddit},
    {"name": "TikTok", "label": "KEMUNGKINAN AKTIF", "check": _check_tiktok},
    {"name": "Medium", "label": "KEMUNGKINAN AKTIF", "check": _check_medium},
    {"name": "Vimeo", "label": "KEMUNGKINAN AKTIF", "check": _check_vimeo},
    {"name": "VK", "label": "KEMUNGKINAN AKTIF", "check": _check_vk},
]


async def sherlock_search(username: str, on_progress=None) -> dict:
    start = time.monotonic()
    source = "sherlock/py"

    try:
        found_platforms = []
        for platform in PLATFORMS:
            if on_progress:
                on_progress(platform["name"], "checking")
            try:
                is_found = await platform["check"](username, None)
                if is_found:
                    found_platforms.append(f"{platform['name']} ({platform['label']})")
                    if on_progress:
                        on_progress(platform["name"], "found")
                else:
                    if on_progress:
                        on_progress(platform["name"], "not_found")
            except Exception:
                if on_progress:
                    on_progress(platform["name"], "error")

        return {
            "success": True,
            "data": {"username": username, "foundPlatforms": found_platforms},
            "meta": {"source": source, "duration_ms": int((time.monotonic() - start) * 1000)},
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "meta": {"source": source, "duration_ms": int((time.monotonic() - start) * 1000)},
        }
