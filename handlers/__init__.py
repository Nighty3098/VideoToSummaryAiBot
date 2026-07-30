from telethon import TelegramClient

from config import BOT_TOKEN

_bot: TelegramClient = None


def set_bot(client: TelegramClient):
    global _bot
    _bot = client


def get_bot() -> TelegramClient:
    return _bot
