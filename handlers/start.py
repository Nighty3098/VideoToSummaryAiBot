import logging

from telethon import Button, events
from telethon.events import NewMessage, CallbackQuery

from database import get_user_lang, set_user_lang, is_user_allowed, upsert_user_profile
from config import ADMIN_ID
from messages import get

logger = logging.getLogger(__name__)


async def _save_profile(event, user_id: int):
    try:
        sender = await event.get_sender()
        username = getattr(sender, "username", "") or ""
        first_name = getattr(sender, "first_name", "") or ""
        upsert_user_profile(user_id, username, first_name)
    except Exception as e:
        logger.warning(f"Could not save profile for {user_id}: {e}")

LANG_BUTTONS = [
    [Button.inline("English", b"lang_en")],
    [Button.inline("Русский", b"lang_ru")],
]


async def _ask_language(event):
    # First contact is always in English, with an offer to switch language.
    text = get("start.welcome", lang="en") + "\n\n" + get("start.choose_language", lang="en")
    await event.reply(text, buttons=LANG_BUTTONS)


def register(client):
    @client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event: NewMessage.Event):
        uid = event.sender_id
        if uid is None:
            return
        await _save_profile(event, uid)
        lang = get_user_lang(uid)
        if lang:
            await event.reply(get("start.welcome", lang=lang))
        else:
            await _ask_language(event)

    @client.on(events.NewMessage(pattern=r"^/lang"))
    async def lang_command(event: NewMessage.Event):
        uid = event.sender_id
        if uid is None:
            return
        await _ask_language(event)

    @client.on(events.CallbackQuery(pattern=b"lang_"))
    async def lang_callback(event: CallbackQuery.Event):
        data = event.data.decode()
        lang = data.split("_")[1]
        if lang not in ("en", "ru"):
            return
        uid = event.sender_id
        if uid is None:
            return
        await _save_profile(event, uid)
        set_user_lang(uid, lang)
        await event.answer()
        text = get("start.choose_language_done", lang=lang)
        if not (is_user_allowed(uid) or uid == ADMIN_ID):
            text += "\n\n" + get("start.needs_access", lang=lang)
        text += "\n\n" + get("start.welcome", lang=lang)
        await event.edit(text)