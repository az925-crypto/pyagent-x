from .scan import scan_target
from .sherlock import sherlock_search
from .ig.profile import ig_profile
from .ig.followers import ig_followers
from .ig.following import ig_following
from .ig.media import ig_media
from .ig.download import ig_download


async def run_ig(username: str, on_progress=None):
    result = await ig_profile(username)
    return result


async def run_scan(target: str):
    return await scan_target(target)


async def run_sherlock(username: str, on_progress=None):
    return await sherlock_search(username, on_progress)


async def run_ig_followers(username: str, on_progress=None):
    return await ig_followers(username)


async def run_ig_following(username: str, on_progress=None):
    return await ig_following(username)


async def run_ig_media(username: str, amount: int = 5, on_progress=None):
    return await ig_media(username, amount)


async def run_ig_download(username: str, amount: int = 5, on_progress=None):
    return await ig_download(username, amount)
