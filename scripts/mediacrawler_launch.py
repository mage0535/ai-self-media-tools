"""Run MediaCrawler (cwd = its checkout, its own venv) headless for one small search.

MediaCrawler is used unmodified (NON-COMMERCIAL LEARNING LICENSE 1.1, see its LICENSE).
Only runtime settings are patched here:
- the login QR is saved to $MC_QR_PNG for the account holder to scan, instead of a desktop window;
- with MC_UNATTENDED=1 a needed login stops the run (exit 3) instead of waiting for a scan;
- with $MC_COOKIE_FILE (a Playwright storage state) its cookies log in, so they never appear in argv;
- Zhihu search asks for its most-upvoted works of the last three months;
- a slider captcha stops the run (exit 4); it is never solved automatically (no anti-bot bypass);
- no CDP, no comments, login state kept in browser_data/ (the root-only profile dir).
"""
import base64
import io
import json
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())

import config  # noqa: E402  (MediaCrawler's config package)
from PIL import Image  # noqa: E402
from playwright.async_api import BrowserType  # noqa: E402
from media_platform.douyin.login import DouYinLogin  # noqa: E402
from media_platform.zhihu.client import ZhiHuClient  # noqa: E402
from media_platform.zhihu.field import SearchSort, SearchTime  # noqa: E402
from tools import crawler_util, utils  # noqa: E402

LOGIN_REQUIRED = 3
VERIFICATION_REQUIRED = 4


def save_qrcode(qr_code: str) -> None:
    if os.environ.get("MC_UNATTENDED") == "1":
        print("mediacrawler_login_required", flush=True)
        os._exit(LOGIN_REQUIRED)
    Image.open(io.BytesIO(base64.b64decode(qr_code.split(",")[-1]))).save(os.environ["MC_QR_PNG"])
    print("mediacrawler_qr_saved", flush=True)


async def stop_at_slider(self, *args, **kwargs) -> None:
    print("mediacrawler_verification_required", flush=True)
    os._exit(VERIFICATION_REQUIRED)


def without_chrome_channel(launch):
    # The server has Playwright's Chromium, not Google Chrome.
    async def wrapped(self, *args, **kwargs):
        kwargs.pop("channel", None)
        return await launch(self, *args, **kwargs)
    return wrapped


def hot_zhihu_search(search):
    # Hot works: Zhihu's own most-upvoted ordering within three months (the crawler passes neither).
    async def wrapped(self, *args, **kwargs):
        kwargs.setdefault("sort", SearchSort.UPVOTED_COUNT)
        kwargs.setdefault("search_time", SearchTime.THREE_MONTH)
        return await search(self, *args, **kwargs)
    return wrapped


ZhiHuClient.get_note_by_keyword = hot_zhihu_search(ZhiHuClient.get_note_by_keyword)
crawler_util.show_qrcode = utils.show_qrcode = save_qrcode
DouYinLogin.move_slider = stop_at_slider
BrowserType.launch = without_chrome_channel(BrowserType.launch)
BrowserType.launch_persistent_context = without_chrome_channel(BrowserType.launch_persistent_context)
config.ENABLE_CDP_MODE = False
config.SAVE_LOGIN_STATE = True
config.ENABLE_GET_COMMENTS = False
config.ENABLE_GET_SUB_COMMENTS = False
config.ENABLE_GET_WORDCLOUD = False
if os.environ.get("MC_COOKIE_FILE"):
    with open(os.environ["MC_COOKIE_FILE"], encoding="utf-8") as handle:
        state = json.load(handle)
    cookies = state.get("cookies", []) if isinstance(state, dict) else state
    config.COOKIES = "; ".join(f"{row['name']}={row['value']}" for row in cookies if row.get("name"))
    config.LOGIN_TYPE = "cookie"

sys.argv = ["main.py", *sys.argv[1:]]
runpy.run_path("main.py", run_name="__main__")
