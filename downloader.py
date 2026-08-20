import os
import re
import time
import shutil
import asyncio
import logging
from pathlib import Path

import yt_dlp

from config import (
    USE_SOCKS5,
    SOCKS5_PROXY,
    YOUTUBE_COOKIES,
    YOUTUBE_COOKIES_FROM_BROWSER,
    YOUTUBE_EXTRACTOR_ARGS,
)
from proxy_utils import socks5_health

logger = logging.getLogger(__name__)

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)/"
)


def _progress_hook(kv):
    if kv.get("status") == "downloading":
        pct = kv.get("_percent_str", "?.?%").strip()
        logger.info(f"yt-dlp: {pct} downloaded")


def is_youtube_url(text: str) -> bool:
    return bool(YOUTUBE_RE.search(text))


def _get_proxy_opts() -> dict:
    if USE_SOCKS5 == "1" and SOCKS5_PROXY:
        exit_ip = socks5_health(SOCKS5_PROXY)
        if exit_ip:
            logger.info(f"Using SOCKS5 proxy for download: {SOCKS5_PROXY} (exit IP: {exit_ip})")
            return {"proxy": SOCKS5_PROXY, "socket_timeout": 30}
        else:
            logger.warning(f"SOCKS5 proxy {SOCKS5_PROXY} unreachable, falling back to direct")
    return {}


def _session_opts() -> dict:
    """YouTube session quality: cookies + player clients + po_token/consent args."""
    opts = {}
    if YOUTUBE_COOKIES and os.path.exists(YOUTUBE_COOKIES):
        opts["cookies"] = YOUTUBE_COOKIES
    elif YOUTUBE_COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (YOUTUBE_COOKIES_FROM_BROWSER,)
    user_args = []
    if YOUTUBE_EXTRACTOR_ARGS:
        user_args = [a.strip() for a in YOUTUBE_EXTRACTOR_ARGS.split(",") if a.strip()]
    # web/ios clients: android client now maps to android-vr whose media URLs
    # often return HTTP 403 through this SOCKS5 proxy
    if not any("player_client" in a for a in user_args):
        user_args.append("player_client=web,ios")
    if user_args:
        opts["extractor_args"] = {"youtube": user_args}
    return opts


def _js_runtime_opts() -> dict:
    """Enable an external JS runtime (deno/node) for extraction, if available."""
    for name in ("deno", "node", "bun", "quickjs"):
        path = shutil.which(name)
        if path:
            logger.info(f"Using JS runtime for yt-dlp: {name} ({path})")
            return {"js_runtimes": {name: {"path": path}}}
    logger.warning("No JS runtime (deno/node) found; YouTube extraction may get HTTP 403")
    return {}


_RETRY_MARKERS = (
    "HTTP Error 429",
    "HTTP Error 403",
    "Sign in to confirm",
    "Too Many Requests",
    "consent",
    "Connection refused",
    "Connection reset",
    "TLS",
    "timed out",
    "Read timeout",
)


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc)
    return any(marker in msg for marker in _RETRY_MARKERS)


def extract_youtube_video_id(url: str) -> str | None:
    """
    Fast extraction of video ID without downloading.
    Returns video_id or None on failure.
    """
    try:
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "extract_flat": True,
                **_session_opts(),
                **_get_proxy_opts(),
                **_js_runtime_opts(),
            }
        ) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("id")
    except Exception as e:
        logger.warning(f"Failed to extract video ID: {e}")
        return None


async def download_youtube_audio(url: str, work_dir: str) -> tuple[str, str, str]:
    """
    Download audio from a YouTube video.
    Returns (audio_path, subtitles_path_or_None, video_title).
    Subtitles download is best-effort (failures are ignored).
    """
    loop = asyncio.get_running_loop()

    def _sync_audio():
        outtmpl = os.path.join(work_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            "format": "worstaudio/worst",
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                }
            ],
            "quiet": True,
            "progress_hooks": [_progress_hook],
            "skip_download": False,
            "extract_flat": False,
            # no writesubtitles here - done separately to avoid 429
            **_session_opts(),
            **_get_proxy_opts(),
            **_js_runtime_opts(),
        }
        last_err: Exception | None = None
        alternate_clients = [
            "player_client=mweb,web",
            "player_client=web,android_creator",
            "player_client=web",
        ]
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    audio_path = os.path.join(work_dir, f"{info['id']}.mp3")
                    title = info.get("title", "")
                    return audio_path, info["id"], title
            except Exception as e:
                last_err = e
                if not _is_retryable(e) or attempt == 2:
                    raise
                backoff = 30 * (attempt + 1)
                logger.warning(
                    f"YouTube blocked/errored (attempt {attempt + 1}/3), retrying in {backoff}s: {e}"
                )
                # switch player client on retry - some clients' media URLs are
                # intermittently rejected by googlevideo through this proxy
                if alternate_clients:
                    ydl_opts["extractor_args"] = {
                        "youtube": [alternate_clients.pop(0)]
                    }
                time.sleep(backoff)
        if last_err:
            raise last_err
        raise RuntimeError("audio download failed without an exception")

    audio_path, video_id, video_title = await loop.run_in_executor(None, _sync_audio)

    subs_path = await _try_download_subs(url, video_id, work_dir, loop)

    return audio_path, subs_path, video_title


async def _try_download_subs(
    url: str, video_id: str, work_dir: str, loop: asyncio.AbstractEventLoop
) -> str | None:
    """
    Best-effort subtitle download. Failures are logged and ignored.
    """
    def _sync():
        outtmpl = os.path.join(work_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            "quiet": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "skip_download": True,
            "outtmpl": outtmpl,
            **_session_opts(),
            **_get_proxy_opts(),
            **_js_runtime_opts(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
        for lang in ("ru", "en"):
            candidate = os.path.join(work_dir, f"{video_id}.{lang}.vtt")
            if os.path.exists(candidate):
                return candidate
        return None

    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.warning(f"Subtitle download failed (non-critical): {e}")
        return None


async def download_telegram_file(
    message, work_dir: str, file_name: str
) -> tuple[str, str]:
    """
    Download a file from a Telegram message.
    Returns (downloaded_path, None) - subtitles not applicable.
    """
    ext = Path(file_name).suffix.lower()
    dest = os.path.join(work_dir, f"telegram_input{ext}")
    path = await message.download_media(file=dest)
    return path, None
