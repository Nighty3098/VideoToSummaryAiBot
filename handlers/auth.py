from database import is_user_allowed
from config import ADMIN_ID


def auth_required(func):
    async def wrapper(event):
        user_id = event.sender_id
        if user_id is None:
            return
        if user_id == ADMIN_ID:
            return await func(event)
        if not is_user_allowed(user_id):
            return
        return await func(event)
    return wrapper
