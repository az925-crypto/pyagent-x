import os
import io
import sys
import time
import tempfile
from pathlib import Path

import logging
for _lg in ("instagrapi", "instagrapi.mixins", "instagrapi.extractors",
            "instagrapi.mixins.media", "instagrapi.mixins.auth",
            "urllib3", "urllib3.connectionpool"):
    logging.getLogger(_lg).setLevel(logging.CRITICAL)


class _SuppressInstaErrors:
    """Context manager that suppresses instagrapi's stderr noise
    (exception chaining tracebacks, 429 warnings, etc.)"""
    def __enter__(self):
        self._stderr = sys.stderr
        sys.stderr = io.StringIO()
        return self

    def __exit__(self, *args):
        sys.stderr = self._stderr


SESSION_FILE = Path(tempfile.gettempdir()) / ".agent-x-ig-session.json"
IG_USER = os.environ.get("IG_USERNAME", "")
IG_PASS = os.environ.get("IG_PASSWORD", "")
IG_SID = os.environ.get("IG_SESSIONID", "")

_client_cache = None
_client_last_used = 0
_CLIENT_TTL = 300


def _make_client():
    from instagrapi import Client
    cl = Client()
    cl.delay_range = [5, 12]
    cl.request_timeout = 45
    cl.set_user_agent(
        "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
    )
    cl.set_device({
        "manufacturer": "Samsung",
        "model": "SM-S901B",
        "android_version": 13,
        "android_release": "12.0.0",
        "dpi": "420dpi",
        "resolution": "1080x2280",
        "chipset": "exynos2200",
    })
    if SESSION_FILE.exists():
        try:
            cl.load_settings(str(SESSION_FILE))
        except Exception:
            pass
    if IG_SID:
        try:
            cl.login_by_sessionid(IG_SID)
            return cl
        except Exception:
            pass
    if IG_USER and IG_PASS:
        cl.login(IG_USER, IG_PASS)
        cl.dump_settings(str(SESSION_FILE))
        return cl
    raise ValueError("IG_USERNAME/PASSWORD or IG_SESSIONID required")


def _patch_extractors():
    """Monkey-patch extract_media_v1 to handle missing video/image fields.
    Suppresses stderr during the operation to hide internal tracebacks."""
    try:
        import instagrapi.extractors
        import instagrapi.mixins.media
        _orig = instagrapi.extractors.extract_media_v1

        def _safe_extract(media):
            if not media.get("video_versions"):
                media["video_versions"] = [{"url": "", "height": 1, "width": 1}]
            if not media.get("image_versions2") or not media["image_versions2"].get("candidates"):
                media["image_versions2"] = {"candidates": [{"url": "", "height": 1, "width": 1}]}
            try:
                return _orig(media)
            except (IndexError, KeyError, TypeError):
                return None

        instagrapi.extractors.extract_media_v1 = _safe_extract
        instagrapi.mixins.media.extract_media_v1 = _safe_extract
    except Exception:
        pass


with _SuppressInstaErrors():
    _patch_extractors()


def get_client():
    global _client_cache, _client_last_used
    now = time.time()
    if _client_cache is not None and (now - _client_last_used) < _CLIENT_TTL:
        _client_last_used = now
        return _client_cache
    _client_cache = _make_client()
    _client_last_used = now
    return _client_cache
