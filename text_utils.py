import re
import html
import logging

from config import QWEN_MAX_PROMPT_CHARS, QWEN_PROMPT_OVERHEAD

logger = logging.getLogger(__name__)

TEXT_LIMIT = QWEN_MAX_PROMPT_CHARS - QWEN_PROMPT_OVERHEAD

_TIMESTAMP_LINE_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}\.\d{3}.*$"
)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_TS_PREFIX_RE = re.compile(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*")
_SPACE_RE = re.compile(r"\s+")


def clean_vtt(text: str) -> str:
    """Remove VTT timestamps, HTML tags/entities, duplicate lines."""
    if not text:
        return ""
    lines_out = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT":
            continue
        if _TIMESTAMP_LINE_RE.match(line):
            continue
        line = _HTML_TAG_RE.sub("", line)
        line = html.unescape(line)
        line = _SPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        lines_out.append(line)

    dedup = []
    for line in lines_out:
        if not dedup or line != dedup[-1]:
            dedup.append(line)
    return "\n".join(dedup)


def clean_transcription(text: str) -> str:
    """Remove [MM:SS] / [H:MM:SS] timestamp prefixes and normalize spaces."""
    if not text:
        return ""
    lines_out = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = _TS_PREFIX_RE.sub("", line)
        line = _SPACE_RE.sub(" ", line).strip()
        if line:
            lines_out.append(line)
    return "\n".join(lines_out)


def select_for_qwen(
    transcription: str,
    subtitles: str | None = None,
    limit: int = TEXT_LIMIT,
) -> tuple[str, str]:
    """
    Choose the best text to send to Qwen.
    Returns (text, source) where source is one of:
    'combined', 'subtitles', 'transcription', 'transcription_truncated'.
    """
    trans = clean_transcription(transcription)
    subs = clean_vtt(subtitles) if subtitles else ""

    if subs and trans:
        combined = f"=== SUBTITLES ===\n{subs}\n\n=== WHISPER TRANSCRIPTION ===\n{trans}"
    elif subs:
        combined = f"=== SUBTITLES ===\n{subs}"
    else:
        combined = f"=== WHISPER TRANSCRIPTION ===\n{trans}"

    if len(combined) <= limit:
        return combined, "combined"

    if subs and len(subs) <= limit:
        logger.info("Combined text too large, sending only subtitles")
        return f"=== SUBTITLES ===\n{subs}", "subtitles"

    if len(trans) <= limit:
        logger.info("Subtitles too large, sending only transcription")
        return f"=== WHISPER TRANSCRIPTION ===\n{trans}", "transcription"

    logger.warning("Transcription too large, truncating")
    return f"=== WHISPER TRANSCRIPTION ===\n{trans[:limit]}", "transcription_truncated"
