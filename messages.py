import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
_MSGS = None


def _load() -> dict:
    global _MSGS
    if _MSGS is None:
        with open(os.path.join(_BASE, "messages.json"), "r", encoding="utf-8") as f:
            _MSGS = json.load(f)
    return _MSGS


def get(key: str, **kwargs) -> str:
    parts = key.split(".")
    val = _load()
    for p in parts:
        val = val[p]
    if kwargs:
        return val.format(**kwargs)
    return val
