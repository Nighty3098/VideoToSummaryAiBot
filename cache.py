import os
import json
import hashlib
import logging

from config import CACHE_DIR

logger = logging.getLogger(__name__)


def _path(cache_key: str, *parts: str) -> str:
    return os.path.join(CACHE_DIR, cache_key, *parts)


def youtube_key(video_id: str) -> str:
    return f"yt_{video_id}"


def file_key(filepath: str) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
    except Exception:
        return ""
    return f"file_{h.hexdigest()[:16]}"


def is_cached(cache_key: str, resource: str) -> bool:
    return os.path.isfile(_path(cache_key, resource))


def get_path(cache_key: str, resource: str) -> str | None:
    p = _path(cache_key, resource)
    return p if os.path.isfile(p) else None


def get_text(cache_key: str, resource: str) -> str | None:
    p = get_path(cache_key, resource)
    if p:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_bytes(cache_key: str, resource: str) -> bytes | None:
    p = get_path(cache_key, resource)
    if p:
        with open(p, "rb") as f:
            return f.read()
    return None


def set_file(cache_key: str, resource: str, source_path: str):
    dest = _path(cache_key, resource)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    import shutil
    shutil.copy2(source_path, dest)
    logger.info(f"Cached {resource} for {cache_key}")


def set_text(cache_key: str, resource: str, text: str):
    dest = _path(cache_key, resource)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"Cached {resource} for {cache_key}")


def get_meta(cache_key: str) -> dict:
    p = _path(cache_key, "meta.json")
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def set_meta(cache_key: str, **kwargs):
    dest = _path(cache_key, "meta.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    existing = get_meta(cache_key)
    existing.update(kwargs)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)


def clear(cache_key: str):
    path = _path(cache_key)
    if os.path.isdir(path):
        import shutil
        shutil.rmtree(path)
        logger.info(f"Cleared cache for {cache_key}")
