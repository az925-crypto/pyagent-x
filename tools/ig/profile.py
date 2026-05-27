import time
from ._shared import get_client, _SuppressInstaErrors


def _ents(users):
    return [
        {
            "username": u.username,
            "fullName": u.full_name,
            "isPrivate": u.is_private,
            "isVerified": u.is_verified,
        }
        for u in (users or {}).values()
    ]


async def ig_profile(username: str) -> dict:
    t0 = time.monotonic()
    try:
        with _SuppressInstaErrors():
            cl = get_client()
            user = cl.user_info_by_username(username)
        p = {
            "username": user.username,
            "fullName": user.full_name,
            "biography": user.biography or "",
            "isPrivate": user.is_private,
            "isVerified": user.is_verified,
            "followerCount": user.follower_count,
            "followingCount": user.following_count,
            "mediaCount": user.media_count,
            "profilePicUrl": str(user.profile_pic_url or ""),
            "externalUrl": user.external_url,
            "publicEmail": getattr(user, "public_email", None),
            "contactPhoneNumber": getattr(user, "contact_phone_number", None),
            "isBusiness": user.is_business,
        }
        fl, fg = [], []
        try:
            with _SuppressInstaErrors():
                fg = _ents(cl.user_following(user.pk, amount=100))
        except Exception:
            pass
        try:
            with _SuppressInstaErrors():
                fl = _ents(cl.user_followers(user.pk, amount=100))
        except Exception:
            pass
        return {
            "success": True,
            "data": {"profile": p, "followingList": fg, "followerList": fl},
            "meta": {"source": "instagrapi", "duration_ms": int((time.monotonic() - t0) * 1000)},
        }
    except ImportError:
        return {"success": False, "error": "instagrapi not installed. pip install instagrapi"}
    except Exception as e:
        return {"success": False, "error": str(e)}
