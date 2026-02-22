import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

log = logging.getLogger("bot")


async def start_bot():
    from config import get_settings
    settings = get_settings()
    bot = Bot(token=settings.BOT_TOKEN)
    await dp.start_polling(bot)

    webapp_url = os.getenv("WEBAPP_URL", "")
    admin_tg   = int(os.getenv("ADMIN_TG_ID", "0"))

    @dp.message(Command("start"))
    async def cmd_start(msg: Message):
        keyboard = None
        if webapp_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🚀 Открыть SKINTEL",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]])

        await msg.answer(
            "⚔️ <b>SKINTEL — CS2 Arbitrage Terminal</b>\n\n"
            "Трекер арбитража между Buff, CSGOMarket, Skinport и Steam.\n\n"
            "Чтобы начать — нажми кнопку ниже и введи ключ доступа.\n"
            "Если ключа нет — обратись к администратору.",
            reply_markup=keyboard,
        )

    @dp.message(Command("genkey"))
    async def cmd_genkey(msg: Message):
        if msg.from_user.id != admin_tg:
            await msg.answer("⛔️ Только для администратора")
            return

        args = msg.text.split(maxsplit=2)
        note = args[1] if len(args) > 1 else ""
        perm = "--perm" in msg.text

        # Генерируем ключ через API
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/api/admin/genkey",
                json={"admin_tg_id": admin_tg, "note": note, "permanent": perm}
            ) as resp:
                data = await resp.json()

        key = data.get("key", "ошибка")
        key_type = "♾️ многоразовый" if perm else "1️⃣ одноразовый"
        await msg.answer(
            f"✅ <b>Ключ создан ({key_type})</b>\n\n"
            f"<code>{key}</code>\n\n"
            f"📝 Описание: {note or '—'}\n\n"
            f"Передай этот ключ пользователю.",
        )

    @dp.message(Command("keys"))
    async def cmd_keys(msg: Message):
        if msg.from_user.id != admin_tg:
            await msg.answer("⛔️ Только для администратора")
            return

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://localhost:8000/api/admin/keys?admin_tg_id={admin_tg}"
            ) as resp:
                keys = await resp.json()

        if not keys:
            await msg.answer("Ключей нет")
            return

        lines = ["<b>Все ключи:</b>\n"]
        for k in keys[:20]:
            status = "✅ использован" if k["is_used"] else "🆓 свободен"
            perm   = " ♾️" if k["is_permanent"] else ""
            lines.append(
                f"<code>{k['key']}</code>{perm} — {status}"
                + (f"\n   👤 tg:{k['used_by_tg']}" if k["used_by_tg"] else "")
                + (f"\n   📝 {k['note']}" if k["note"] else "")
            )
        await msg.answer("\n".join(lines))

    @dp.message(Command("status"))
    async def cmd_status(msg: Message):
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://localhost:8000/api/auth/check?tg_id={msg.from_user.id}"
            ) as resp:
                data = await resp.json()

        if data.get("has_access"):
            await msg.answer(
                f"✅ У тебя есть доступ к SKINTEL\n"
                f"👤 {data.get('first_name', '')} @{data.get('username', '')}"
            )
        else:
            await msg.answer("❌ Нет доступа. Введи ключ активации в приложении.")

    @dp.message(Command("help"))
    async def cmd_help(msg: Message):
        is_admin = msg.from_user.id == admin_tg
        text = (
            "📖 <b>SKINTEL — Команды</b>\n\n"
            "/start — запустить бота\n"
            "/status — проверить доступ\n"
            "/help — эта справка\n"
        )
        if is_admin:
            text += (
                "\n<b>Admin:</b>\n"
                "/genkey [описание] — создать ключ\n"
                "/genkey --perm [описание] — многоразовый ключ\n"
                "/keys — список всех ключей\n"
            )
        await msg.answer(text)

    log.info("Telegram бот готов, запускаю polling...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
