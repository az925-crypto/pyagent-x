import time
from ._shared import get_client, _SuppressInstaErrors


def _safe_call(func, *args):
    try:
        with _SuppressInstaErrors():
            return func(*args)
    except Exception:
        return None


async def ig_media(username: str, amount: int = 5) -> dict:
    t0 = time.monotonic()
    try:
        cl = get_client()
        user_id = _safe_call(cl.user_id_from_username, username)
        if not user_id:
            return {"success": False, "error": f"User {username} not found"}
        medias = _safe_call(cl.user_medias, user_id, amount)
        if not medias:
            return {"success": False, "error": "Failed to fetch media / no media available"}
        result = []
        for m in medias:
            if m is None:
                continue
            item = {
                "id": m.pk,
                "code": m.code,
                "media_type": m.media_type,
                "caption": m.caption_text,
                "like_count": m.like_count,
                "comment_count": m.comment_count,
                "taken_at": str(m.taken_at),
            }
            comments = _safe_call(cl.media_comments, m.pk, 20)
            if comments:
                item["comments"] = [
                    {"username": c.user.username, "text": c.text, "pk": c.pk}
                    for c in comments
                ]
            likers = _safe_call(cl.media_likers, m.pk)
            if likers:
                item["likers"] = [u.username for u in likers]
            result.append(item)
        return {
            "success": True,
            "data": {"target": username, "total_posts": len(result), "posts": result},
            "meta": {"source": "instagrapi", "duration_ms": int((time.monotonic() - t0) * 1000)},
        }
    except ImportError:
        return {"success": False, "error": "instagrapi not installed. pip install instagrapi"}
    except Exception as e:
        return {"success": False, "error": str(e)}
