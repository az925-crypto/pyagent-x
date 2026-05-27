import time
from ._shared import get_client, _SuppressInstaErrors


async def ig_followers(username: str) -> dict:
    t0 = time.monotonic()
    try:
        with _SuppressInstaErrors():
            cl = get_client()
            user_id = cl.user_id_from_username(username)
            followers = cl.user_followers(user_id, amount=100)
        return {
            "success": True,
            "data": {
                "target": username,
                "total_followers": len(followers),
                "followers": [
                    {"username": u.username, "pk": u.pk, "full_name": u.full_name, "is_private": u.is_private}
                    for u in followers.values()
                ],
            },
            "meta": {"source": "instagrapi", "duration_ms": int((time.monotonic() - t0) * 1000)},
        }
    except ImportError:
        return {"success": False, "error": "instagrapi not installed. pip install instagrapi"}
    except Exception as e:
        return {"success": False, "error": str(e)}
