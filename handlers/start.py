import logging

from telethon import events
from telethon.events import NewMessage

from handlers.auth import auth_required
from messages import get

logger = logging.getLogger(__name__)


def register(client):
    @client.on(events.NewMessage(pattern="/start"))
    @auth_required
    async def start_handler(event: NewMessage.Event):
        await event.reply(get("start.welcome"))
