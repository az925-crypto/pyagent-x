import time
from pathlib import Path
from ._shared import get_client, _SuppressInstaErrors

DL_DIR = Path(__file__).parent / "downloads"


def _safe_call(func, *args):
    try:
        with _SuppressInstaErrors():
            return func(*args)
    except Exception:
        return None


async def ig_download(username: str, amount: int = 5) -> dict:
    t0 = time.monotonic()
    try:
        cl = get_client()
        user_id = _safe_call(cl.user_id_from_username, username)
        if not user_id:
            return {"success": False, "error": f"User {username} not found"}
        medias = _safe_call(cl.user_medias, user_id, amount)
        if not medias:
            return {"success": False, "error": "Failed to fetch media / no media available"}
        DL_DIR.mkdir(parents=True, exist_ok=True)
        result = []
        for m in medias:
            if m is None:
                continue
            item = {
                "id": m.pk,
                "code": m.code,
                "media_type": m.media_type,
                "caption": (m.caption_text or "")[:100],
                "taken_at": str(m.taken_at),
            }
            try:
                if m.media_type == 1:
                    path = cl.photo_download(m.pk, str(DL_DIR))
                    item["download_path"] = str(path)
                elif m.media_type == 2:
                    path = cl.video_download(m.pk, str(DL_DIR))
                    item["download_path"] = str(path)
                elif m.media_type == 8:
                    paths = cl.album_download(m.pk, str(DL_DIR))
                    item["download_paths"] = [str(p) for p in (paths if isinstance(paths, list) else [paths])]
                else:
                    item["download_path"] = None
            except Exception as e:
                item["download_error"] = str(e)
            result.append(item)
        return {
            "success": True,
            "data": {
                "target": username,
                "download_dir": str(DL_DIR),
                "total_downloaded": len([p for p in result if p.get("download_path") or p.get("download_paths")]),
                "items": result,
            },
            "meta": {"source": "instagrapi", "duration_ms": int((time.monotonic() - t0) * 1000)},
        }
    except ImportError:
        return {"success": False, "error": "instagrapi not installed. pip install instagrapi"}
    except Exception as e:
        return {"success": False, "error": str(e)}
