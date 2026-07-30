import os
import shutil
import logging
from datetime import datetime

from telethon import events, Button
from telethon.events import NewMessage, CallbackQuery

from database import (
    get_stats,
    reset_stats,
    get_allowed_users,
    get_allowed_users_count,
    add_user,
    remove_user,
)
from config import ADMIN_ID, TEMP_DIR, LOGS_DIR
from messages import get

logger = logging.getLogger(__name__)

_waiting_for_add = {}


def register(client):
    @client.on(events.NewMessage(pattern=r"/admin_p"))
    async def admin_panel(event: NewMessage.Event):
        uid = event.sender_id
        if uid != ADMIN_ID:
            return
        await _show_main_menu(event, is_callback=False)

    @client.on(events.CallbackQuery)
    async def callback_handler(event: CallbackQuery.Event):
        uid = event.sender_id
        if uid != ADMIN_ID:
            await event.answer("Access denied.", alert=True)
            return

        data = event.data.decode()
        await event.answer()

        if data == "menu_stats":
            await _show_stats(event)

        elif data == "menu_users":
            await _show_users(event, page=0)

        elif data == "menu_add_user":
            _waiting_for_add[uid] = True
            msg = await event.get_message()
            await msg.edit(
                get("admin.add_user_prompt"),
                buttons=[Button.inline(get("admin.cancel_add"), b"cancel_add")],
            )

        elif data == "cancel_add":
            _waiting_for_add.pop(uid, None)
            await _show_main_menu(event)

        elif data.startswith("remove_user_"):
            target_id = int(data.split("_")[2])
            removed = remove_user(target_id)
            if removed:
                await event.answer(get("admin.remove_success"), alert=True)
            else:
                await event.answer(get("admin.remove_not_found"), alert=True)
            await _show_users(event, page=0)

        elif data.startswith("users_page_"):
            page = int(data.split("_")[2])
            await _show_users(event, page=page)

        elif data == "noop":
            pass

        elif data == "menu_logs":
            await _send_logs(event)

        elif data == "menu_clear_cache":
            await _clear_cache(event)

        elif data == "reset_stats":
            msg = await event.get_message()
            await msg.edit(
                get("admin.reset_confirm"),
                buttons=[
                    [Button.inline("✅ Yes, reset", b"reset_stats_confirm")],
                    [Button.inline(get("admin.back"), b"menu_back")],
                ],
            )

        elif data == "reset_stats_confirm":
            reset_stats()
            await event.answer(get("admin.reset_done"), alert=True)
            await _show_main_menu(event)

        elif data == "menu_back":
            await _show_main_menu(event)

    @client.on(events.NewMessage())
    async def add_user_handler(event: NewMessage.Event):
        uid = event.sender_id
        if uid != ADMIN_ID:
            return
        if uid not in _waiting_for_add:
            return
        if event.raw_text.startswith("/"):
            return
        _waiting_for_add.pop(uid, None)

        target_id = None

        if event.message.forward:
            fwd = event.message.forward
            if fwd.sender_id:
                target_id = fwd.sender_id
                peer = await event.client.get_entity(target_id)
                username = getattr(peer, "username", "") or ""
                first_name = getattr(peer, "first_name", "") or ""
        else:
            try:
                target_id = int(event.raw_text.strip())
            except ValueError:
                await event.reply(get("admin.add_user_invalid"))
                return
            try:
                peer = await event.client.get_entity(target_id)
                username = getattr(peer, "username", "") or ""
                first_name = getattr(peer, "first_name", "") or ""
            except Exception:
                username = ""
                first_name = ""

        if not target_id:
            await event.reply(get("admin.add_user_no_id"))
            return

        add_user(target_id, username, first_name, ADMIN_ID)
        await event.reply(get("admin.add_user_success", user_id=target_id, name=first_name))

        try:
            await event.client.send_message(target_id, get("admin.notify_new_user"))
        except Exception:
            logger.warning(get("admin.notify_failed", user_id=target_id))

        await _show_main_menu(event, is_callback=False)


async def _show_main_menu(event, is_callback: bool = True):
    text = get("admin.panel_title")
    buttons = [
        [Button.inline("📊 Statistics", b"menu_stats"),
         Button.inline("👥 Users", b"menu_users")],
        [Button.inline("➕ Add User", b"menu_add_user")],
        [Button.inline("📋 Logs", b"menu_logs"),
         Button.inline("🧹 Clear Cache", b"menu_clear_cache")],
        [Button.inline("🔄 Reset Stats", b"reset_stats")],
    ]
    if is_callback:
        await event.edit(text, buttons=buttons)
    else:
        await event.reply(text, buttons=buttons)


async def _send_logs(event):
    log_path = os.path.join(LOGS_DIR, f"bot_{datetime.now().strftime('%Y-%m-%d')}.log")
    if not os.path.isfile(log_path):
        await event.edit(get("admin.no_logs"), buttons=[Button.inline(get("admin.back"), b"menu_back")])
        return

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    tail = lines[-200:]
    temp_log = os.path.join(LOGS_DIR, "temp_admin_log.txt")
    with open(temp_log, "w", encoding="utf-8") as f:
        f.writelines(tail)

    await event.client.send_file(
        ADMIN_ID, temp_log,
        caption=get("admin.logs_caption", count=len(tail), filename=os.path.basename(log_path)),
    )
    os.remove(temp_log)

    await _show_main_menu(event)


async def _clear_cache(event):
    await event.edit(get("admin.clearing_cache"))

    for d in (TEMP_DIR, LOGS_DIR):
        if os.path.isdir(d):
            for item in os.listdir(d):
                item_path = os.path.join(d, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    logger.warning(f"Could not remove {item_path}: {e}")

    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    logger.info("Cache cleared manually by admin")
    await event.edit(get("admin.cache_cleared"), buttons=[Button.inline(get("admin.back"), b"menu_back")])


async def _show_stats(event):
    stats = get_stats()
    text = get(
        "admin.stats",
        total_users=stats["total_users"],
        total_requests=stats["total_requests"],
        today_requests=stats["today_requests"],
        completed=stats["completed"],
        errors=stats["errors"],
    )
    await event.edit(text, buttons=[Button.inline(get("admin.back"), b"menu_back")])


async def _show_users(event, page: int):
    users = get_allowed_users(page=page, per_page=10)
    total = get_allowed_users_count()
    total_pages = max(1, (total + 9) // 10)

    lines = [get("admin.users_title", page=page + 1, total_pages=total_pages)]
    for u in users:
        name = u["first_name"] or u["username"] or f"ID {u['user_id']}"
        lines.append(get("admin.user_line", name=name, user_id=u["user_id"]))

    if not users:
        lines.append(get("admin.no_users"))

    text = "\n".join(lines)

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️", f"users_page_{page - 1}"))
    nav_row.append(Button.inline(f"{page + 1}/{total_pages}", b"noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("▶️", f"users_page_{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    remove_row = []
    for u in users[:5]:
        remove_row.append(
            Button.inline(f"❌ {u['user_id']}", f"remove_user_{u['user_id']}")
        )
    if remove_row:
        buttons.append(remove_row)

    buttons.append([Button.inline(get("admin.back"), b"menu_back")])

    await event.edit(text, buttons=buttons)
