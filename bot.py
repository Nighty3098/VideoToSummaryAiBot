import os
import sys
import ctypes

# faster-whisper (ctranslate2) requires libcublas.so.12 from CUDA 12.x.
# On systems with CUDA 13+, this library isn't in standard paths.
# We pre-load it via ctypes.CDLL before ctranslate2 initializes.
_CUBLAS_CANDIDATES = [
    "/usr/local/lib/ollama/cuda_v12",
    "/usr/local/cuda-12/lib64",
    "/usr/local/cuda/lib64",
    "/opt/cuda-12/lib64",
    os.path.expanduser("~/.lmstudio/extensions/backends/vendor/linux-llama-cuda12-vendor-v1"),
]
for p in _CUBLAS_CANDIDATES:
    path = os.path.join(p, "libcublas.so.12")
    if os.path.isfile(path):
        try:
            ctypes.CDLL(path)
            os.environ.setdefault("LD_LIBRARY_PATH", "")
            if p not in os.environ.get("LD_LIBRARY_PATH", ""):
                os.environ["LD_LIBRARY_PATH"] = f"{p}:{os.environ['LD_LIBRARY_PATH']}"
        except Exception:
            pass
        break

from telethon import TelegramClient
from telethon.network import (
    ConnectionTcpFull,
    ConnectionTcpMTProxyRandomizedIntermediate,
)

from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID, USE_PROXY, PROXY_URL
from proxy_utils import parse_tg_proxy
from logger import setup_logger
from database import init_db, ensure_allowed, upsert_user_profile

logger = setup_logger("bot")


def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not set in .env")
        sys.exit(1)

    if not API_ID or not API_HASH:
        logger.critical("API_ID and API_HASH must be set in .env")
        sys.exit(1)

    if not ADMIN_ID:
        logger.critical("ADMIN_ID is not set in .env")
        sys.exit(1)

    logger.info("Initializing database...")
    init_db()
    if ADMIN_ID:
        ensure_allowed(ADMIN_ID)
    logger.info("Database ready.")

    if USE_PROXY == "1" and PROXY_URL:
        server, port, secret = parse_tg_proxy(PROXY_URL)
        if server and port:
            CONNECTION = ConnectionTcpMTProxyRandomizedIntermediate
            PROXY = (server, port, secret)
            logger.info(f"Proxy enabled: {server}:{port}")
        else:
            CONNECTION = ConnectionTcpFull
            PROXY = None
            logger.warning("USE_PROXY=1 but invalid PROXY_URL, falling back to direct.")
    else:
        CONNECTION = ConnectionTcpFull
        PROXY = None
        logger.info("Direct connection (no proxy).")

    client = TelegramClient(
        "bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        connection=CONNECTION,
        proxy=PROXY,
        base_logger=setup_logger("telethon"),
    )

    from handlers import set_bot
    set_bot(client)

    from handlers import start, admin, process
    start.register(client)
    admin.register(client)
    process.register(client)

    logger.info("Starting bot...")
    client.start(bot_token=BOT_TOKEN)

    async def _fill_admin_profile():
        try:
            peer = await client.get_entity(ADMIN_ID)
            upsert_user_profile(
                ADMIN_ID,
                getattr(peer, "username", "") or "",
                getattr(peer, "first_name", "") or "",
            )
            logger.info(f"Admin profile saved: {getattr(peer, 'first_name', '')}")
        except Exception as e:
            logger.warning(f"Could not fetch admin profile: {e}")

    client.loop.create_task(_fill_admin_profile())

    logger.info(f"Bot is running. Admin ID: {ADMIN_ID}")

    client.run_until_disconnected()


if __name__ == "__main__":
    main()
