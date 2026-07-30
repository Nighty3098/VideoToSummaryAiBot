import os
import re
import asyncio
import logging
from pathlib import Path

import yt_dlp

from config import USE_SOCKS5, SOCKS5_PROXY

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
        if _check_socks5(SOCKS5_PROXY):
            logger.info(f"Using SOCKS5 proxy for download: {SOCKS5_PROXY}")
            return {"proxy": SOCKS5_PROXY, "socket_timeout": 10}
        else:
            logger.warning(f"SOCKS5 proxy {SOCKS5_PROXY} unreachable, falling back to direct")
    return {}


def _check_socks5(proxy_url: str) -> bool:
    import re, socket
    m = re.match(r"socks5://([^:@]+)(?::([^@]+))?@([^:]+):(\d+)", proxy_url)
    if not m:
        m = re.match(r"socks5://([^:]+):(\d+)", proxy_url)
        if not m:
            return True
        host, port = m.group(1), int(m.group(2))
    else:
        host, port = m.group(3), int(m.group(4))
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        return True
    except Exception:
        return False


def extract_youtube_video_id(url: str) -> str | None:
    """
    Fast extraction of video ID without downloading.
    Returns video_id or None on failure.
    """
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
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
            **_get_proxy_opts(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_path = os.path.join(work_dir, f"{info['id']}.mp3")
            title = info.get("title", "")
            return audio_path, info["id"], title

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
            **_get_proxy_opts(),
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
    loop = asyncio.get_running_loop()

    def _sync():
        return message.download_media(file=dest)

    path = await loop.run_in_executor(None, _sync)
    return path, None
