import os
import asyncio
import logging

from faster_whisper import WhisperModel

from config import WHISPER_MODEL, WHISPER_CACHE_DIR

logger = logging.getLogger(__name__)

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info(f"Loading Whisper model '{WHISPER_MODEL}'...")
        kwargs = {
            "model_size_or_path": WHISPER_MODEL,
            "device": "cuda",
            "compute_type": "float16",
            "download_root": WHISPER_CACHE_DIR or None,
        }
        _model = WhisperModel(**kwargs)
        logger.info("Whisper model loaded.")
    return _model


async def transcribe(audio_path: str) -> str:
    """
    Transcribe an audio file using faster-whisper.
    Returns full text with basic formatting.
    """
    model = _get_model()
    loop = asyncio.get_running_loop()

    def _sync():
        segments, info = model.transcribe(audio_path, beam_size=5, language=None)
        logger.info(
            f"Transcription detected language: {info.language} "
            f"(probability {info.language_probability:.2f})"
        )
        lines = []
        for seg in segments:
            lines.append(f"[{format_ts(seg.start)}] {seg.text.strip()}")
        return "\n".join(lines)

    return await loop.run_in_executor(None, _sync)


def format_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
