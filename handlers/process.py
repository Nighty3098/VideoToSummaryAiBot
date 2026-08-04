import os
import uuid
import asyncio
import logging
from pathlib import Path

from telethon import events
from telethon.events import NewMessage
from telethon.tl.types import (
    MessageMediaDocument,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
)

from handlers.auth import auth_required
from downloader import is_youtube_url, download_youtube_audio, extract_youtube_video_id
from transcriber import transcribe
from qwen_client import generate_summary
from database import log_request, update_request
from config import ADMIN_ID, TEMP_DIR
from handlers.admin import _waiting_for_add
from messages import get
from cache import youtube_key, file_key, is_cached, set_file, set_text, get_text, get_path, set_meta, get_meta
from text_utils import clean_vtt, clean_transcription, select_for_qwen

logger = logging.getLogger(__name__)


def register(client):
    @client.on(events.NewMessage())
    @auth_required
    async def process_handler(event: NewMessage.Event):
        if event.sender_id in _waiting_for_add:
            return
        if event.sender_id == ADMIN_ID and event.message.forward and not _has_media_file(event):
            return

        text = event.raw_text.strip()
        is_youtube = is_youtube_url(text)

        has_file = _has_media_file(event)

        if not is_youtube and not has_file:
            return

        user_id = event.sender_id
        work_dir = os.path.join(TEMP_DIR, uuid.uuid4().hex)
        os.makedirs(work_dir, exist_ok=True)

        req_id = log_request(
            user_id=user_id,
            req_type="youtube" if is_youtube else "file",
            status="downloading",
        )

        status_msg = await event.reply(get("process.downloading"))
        start_time = _now_ts()

        try:
            cache_key = ""
            audio_path = None
            subtitles_text = None
            video_title = None

            if is_youtube:
                # extract video_id to check cache
                video_id = extract_youtube_video_id(text)
                if video_id:
                    cache_key = youtube_key(video_id)
                    cached = get_meta(cache_key)
                    if cached.get("transcription"):
                        logger.info(f"Cache hit: transcription for {cache_key}")
                        await _update_status(status_msg, "Loading cached transcription...")
                        transcription = clean_transcription(get_text(cache_key, "transcription.txt") or "")
                        subtitles_text = clean_vtt(get_text(cache_key, "subtitles.txt") or "")
                        video_title = cached.get("title", "")
                        if transcription:
                            full_text, source = select_for_qwen(transcription, subtitles_text)
                            logger.info(f"Using text source: {source}")
                            await _send_summary(event, status_msg, work_dir, full_text, video_title, req_id, start_time)
                            return
                    if cached.get("audio"):
                        logger.info(f"Cache hit: audio for {cache_key}")
                        audio_path = get_path(cache_key, "audio.mp3")
                        video_title = cached.get("title", "")

                if not audio_path:
                    last_error = None
                    for attempt in range(5):
                        try:
                            txt = get("process.downloading_youtube", attempt=attempt + 1)
                            await _update_status(status_msg, txt)
                            audio_path, subs_path, video_title = await download_youtube_audio(text, work_dir)
                            if not audio_path:
                                raise RuntimeError("Download failed: no audio file produced")
                            last_error = None
                            break
                        except Exception as e:
                            last_error = e
                            logger.warning(f"Download attempt {attempt + 1}/5 failed: {e}")
                            if attempt < 4:
                                await asyncio.sleep(3)
                    if last_error:
                        raise RuntimeError(f"Download failed after 5 attempts: {last_error}")

                    if cache_key:
                        set_file(cache_key, "audio.mp3", audio_path)

                    if subs_path:
                        subtitles_text = clean_vtt(_read_subs(subs_path))
                        if cache_key:
                            set_text(cache_key, "subtitles.txt", subtitles_text)
                else:
                    # cached audio, need cached subs too
                    subtitles_text = get_text(cache_key, "subtitles.txt")

                file_size = os.path.getsize(audio_path)
                if cache_key:
                    set_meta(cache_key, title=video_title or "")

            elif has_file:
                file_name = _get_file_name(event)
                file_size = _get_file_size(event)
                await _update_status(status_msg, get("process.downloading_file"))
                audio_path, _ = await _download_tg_file(event, work_dir, file_name)
                if not audio_path:
                    raise RuntimeError("File download failed")
                audio_path = _ensure_audio(audio_path, work_dir)
                cache_key = file_key(audio_path)

            update_request(req_id, file_size=file_size)

            # check cached transcription
            if cache_key and is_cached(cache_key, "transcription.txt"):
                logger.info(f"Cache hit: transcription for {cache_key}")
                await _update_status(status_msg, "Loading cached transcription...")
                transcription = clean_transcription(get_text(cache_key, "transcription.txt") or "")
                subtitles_text = clean_vtt(get_text(cache_key, "subtitles.txt") or "")
                if transcription:
                    full_text, source = select_for_qwen(transcription, subtitles_text)
                    logger.info(f"Using text source: {source}")
                    await _send_summary(event, status_msg, work_dir, full_text, video_title, req_id, start_time)
                    return

            await _update_status(status_msg, get("process.transcribing"))
            transcription = await transcribe(audio_path)
            transcription = clean_transcription(transcription)
            logger.info(f"Transcription: {len(transcription)} chars")

            if cache_key:
                set_text(cache_key, "transcription.txt", transcription)
                if subtitles_text:
                    set_text(cache_key, "subtitles.txt", subtitles_text)
                set_meta(cache_key, transcription=True)

            full_text, source = select_for_qwen(transcription, subtitles_text)
            logger.info(f"Using text source: {source}")

            await _update_status(status_msg, get("process.generating_summary"))
            summary = await generate_summary(full_text, video_title=video_title)
            logger.info(f"Summary: {len(summary)} chars")

            if summary.startswith("ERROR:"):
                raise RuntimeError(summary)

            await _update_status(status_msg, get("process.sending_summary"))

            md_path = os.path.join(work_dir, "summary.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(summary)

            await event.client.send_file(
                event.chat_id,
                md_path,
                caption=get("process.success_caption"),
                reply_to=event.id,
            )

            elapsed = _now_ts() - start_time
            update_request(req_id, status="completed", completed_at=_now(), duration_seconds=elapsed)

            try:
                await status_msg.delete()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Processing error (user {user_id}): {e}")
            elapsed = _now_ts() - start_time
            update_request(
                req_id, status="error", error_message=str(e),
                completed_at=_now(), duration_seconds=elapsed,
            )

            if user_id == ADMIN_ID:
                await _update_status(status_msg, f"❌ Error: {e}")
            else:
                await _update_status(status_msg, get("process.error_user"))
                await event.client.send_message(
                    ADMIN_ID,
                    get("process.error_admin", user_id=user_id, error=e, req_id=req_id),
                )


async def _send_summary(event, status_msg, work_dir, full_text, video_title, req_id, start_time):
    await _update_status(status_msg, get("process.generating_summary"))
    summary = await generate_summary(full_text, video_title=video_title)
    logger.info(f"Summary: {len(summary)} chars")

    if summary.startswith("ERROR:"):
        raise RuntimeError(summary)

    await _update_status(status_msg, get("process.sending_summary"))

    md_path = os.path.join(work_dir, "summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(summary)

    await event.client.send_file(
        event.chat_id,
        md_path,
        caption=get("process.success_caption"),
        reply_to=event.id,
    )

    elapsed = _now_ts() - start_time
    update_request(req_id, status="completed", completed_at=_now(), duration_seconds=elapsed)

    try:
        await status_msg.delete()
    except Exception:
        pass


def _has_media_file(event: NewMessage.Event) -> bool:
    media = event.message.media
    if not media:
        return False
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime.startswith("video/") or mime.startswith("audio/"):
            return True
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeAudio) and attr.voice:
                return True
            if isinstance(attr, DocumentAttributeVideo) and attr.round_message:
                return True
    return False


def _get_file_name(event: NewMessage.Event) -> str:
    doc = event.message.media.document
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeAudio) and attr.voice:
            return "voice.ogg"
        if isinstance(attr, DocumentAttributeVideo) and attr.round_message:
            return "round.mp4"
        if hasattr(attr, "file_name") and attr.file_name:
            return attr.file_name
    ext = _mime_to_ext(doc.mime_type)
    return f"file{ext}"


def _get_file_size(event: NewMessage.Event) -> int:
    return event.message.media.document.size


def _mime_to_ext(mime: str) -> str:
    mapping = {
        "video/mp4": ".mp4", "video/webm": ".webm", "video/x-matroska": ".mkv",
        "video/quicktime": ".mov", "video/avi": ".avi",
        "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/wav": ".wav",
        "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/opus": ".opus",
        "audio/flac": ".flac", "audio/aac": ".aac", "audio/m4a": ".m4a",
    }
    return mapping.get(mime, ".bin")


def _read_subs(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _ensure_audio(path: str, work_dir: str) -> str:
    ext = Path(path).suffix.lower()
    audio_exts = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
    if ext in audio_exts:
        return path
    import subprocess
    out = os.path.join(work_dir, "audio.mp3")
    subprocess.run(
        ["ffmpeg", "-i", path, "-vn", "-acodec", "libmp3lame", "-y", out],
        capture_output=True, check=True,
    )
    return out


async def _download_tg_file(event, work_dir: str, file_name: str) -> tuple[str, None]:
    dest = os.path.join(work_dir, file_name)
    path = await event.message.download_media(file=dest)
    return path, None


async def _update_status(msg, text: str):
    try:
        await msg.edit(text)
    except Exception:
        pass


def _now():
    from datetime import datetime
    return datetime.now().isoformat()


def _now_ts():
    import time
    return time.time()
