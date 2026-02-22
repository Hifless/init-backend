import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

log = logging.getLogger("bot")
dp  = Dispatcher()


class BotStates(StatesGroup):
    waiting_buff = State()


# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    webapp_url = os.getenv("WEBAPP_URL", "")
    keyboard = None
    if webapp_url:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🚀 Открыть SKINTEL",
                web_app=WebAppInfo(url=webapp_url),
            )
        ]])

    from database import AsyncSessionLocal
    from auth import get_user_by_tg, has_access
    async with AsyncSessionLocal() as db:
        user = await get_user_by_tg(db, msg.from_user.id)
        access = user is not None and user.access_key is not None

    if access:
        await msg.answer(
            "⚔️ <b>SKINTEL</b> — CS2 Arbitrage Terminal\n\n"
            "✅ Доступ активирован. Нажми кнопку ниже чтобы открыть терминал.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await msg.answer(
            "⚔️ <b>SKINTEL</b> — CS2 Arbitrage Terminal\n\n"
            "Привет! Это закрытый инструмент для поиска арбитража на рынке CS2 скинов.\n\n"
            "<b>Что внутри:</b>\n"
            "📊 Арбитраж Buff → CSGOMarket / Skinport\n"
            "📈 Графики цен за 1д / 7д / 30д / 90д\n"
            "🔔 Алерты по ROI и цене\n"
            "💼 Портфель с таймером разморозки\n"
            "📋 История сделок со статистикой\n\n"
            "🔑 <b>Доступ платный.</b> Для активации введи:\n"
            "<code>/activate ВАШ-КЛЮЧ</code>\n\n"
            "Нет ключа? Пиши @owkfooslq 👇",
            parse_mode="HTML",
        )


# ── /activate ─────────────────────────────────────────────────────────────────
@dp.message(Command("activate"))
async def cmd_activate(msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2:
        await msg.answer("Использование: <code>/activate ВАШ-КЛЮЧ</code>", parse_mode="HTML")
        return

    key = args[1].strip().upper()
    from database import AsyncSessionLocal
    from auth import activate_key
    async with AsyncSessionLocal() as db:
        result = await activate_key(db, key, msg.from_user.id,
                                    username=msg.from_user.username or "")

    if result["ok"]:
        webapp_url = os.getenv("WEBAPP_URL", "")
        keyboard = None
        if webapp_url:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🚀 Открыть SKINTEL",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]])
        await msg.answer(
            "✅ <b>Ключ активирован!</b>\n\nДобро пожаловать в SKINTEL. Нажми кнопку ниже:",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await msg.answer(f"❌ {result['reason']}", parse_mode="HTML")


# ── /buff ─────────────────────────────────────────────────────────────────────
@dp.message(Command("buff"))
async def cmd_buff(msg: Message, state: FSMContext):
    from database import AsyncSessionLocal
    from auth import get_user_by_tg
    async with AsyncSessionLocal() as db:
        user = await get_user_by_tg(db, msg.from_user.id)
        if not user or not user.access_key:
            await msg.answer("❌ Нет доступа.")
            return

    await state.set_state(BotStates.waiting_buff)
    await msg.answer(
        "🍪 <b>Обновление Buff сессии</b>\n\n"
        "Как получить куку:\n"
        "1. Зайди на buff.163.com и залогинься\n"
        "2. F12 → Application → Cookies → buff.163.com\n"
        "3. Найди куку <code>session</code> и скопируй значение\n\n"
        "Вставь значение куки сюда:",
        parse_mode="HTML",
    )


@dp.message(BotStates.waiting_buff)
async def process_buff_cookie(msg: Message, state: FSMContext):
    cookie = msg.text.strip()
    if len(cookie) < 20:
        await msg.answer("❌ Слишком короткое значение. Попробуй снова.")
        return

    from database import AsyncSessionLocal
    from auth import get_user_by_tg
    from datetime import datetime
    async with AsyncSessionLocal() as db:
        user = await get_user_by_tg(db, msg.from_user.id)
        if user:
            user.buff_session = cookie
            user.buff_updated_at = datetime.utcnow()
            await db.commit()

    await state.clear()
    await msg.answer("✅ <b>Buff сессия обновлена!</b>\n\nДанные начнут появляться через ~5 минут.", parse_mode="HTML")


# ── /genkey ───────────────────────────────────────────────────────────────────
@dp.message(Command("genkey"))
async def cmd_genkey(msg: Message):
    from database import AsyncSessionLocal
    from auth import is_owner, create_access_key
    async with AsyncSessionLocal() as db:
        if not await is_owner(db, msg.from_user.id):
            await msg.answer("❌ Нет доступа")
            return
        key = await create_access_key(db, msg.from_user.id)

    await msg.answer(
        f"✅ <b>Ключ создан</b>\n\n"
        f"<code>{key}</code>\n\n"
        f"Одноразовый — передай пользователю.",
        parse_mode="HTML",
    )


# ── /rate ─────────────────────────────────────────────────────────────────────
@dp.message(Command("rate"))
async def cmd_rate(msg: Message):
    from database import AsyncSessionLocal
    from auth import get_user_by_tg
    args = msg.text.split(maxsplit=1)
    if len(args) < 2:
        await msg.answer("Использование: <code>/rate 90.5</code>", parse_mode="HTML")
        return
    try:
        rate = float(args[1].strip().replace(",", "."))
    except ValueError:
        await msg.answer("❌ Неверный формат. Пример: <code>/rate 90.5</code>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as db:
        user = await get_user_by_tg(db, msg.from_user.id)
        if not user or not user.access_key:
            await msg.answer("❌ Нет доступа.")
            return
        user.usd_rub = rate
        await db.commit()

    await msg.answer(f"✅ Курс USD/RUB установлен: <b>{rate}</b>", parse_mode="HTML")


# ── /help ─────────────────────────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    from database import AsyncSessionLocal
    from auth import is_owner
    async with AsyncSessionLocal() as db:
        owner = await is_owner(db, msg.from_user.id)

    text = (
        "📖 <b>SKINTEL — Команды</b>\n\n"
        "/start — запустить бота\n"
        "/activate КЛЮЧ — активировать доступ\n"
        "/buff — обновить Buff сессию\n"
        "/rate 90.5 — установить курс USD/RUB\n"
        "/help — эта справка\n"
    )
    if owner:
        text += (
            "\n<b>Owner:</b>\n"
            "/genkey — создать ключ доступа\n"
        )
    await msg.answer(text, parse_mode="HTML")


# ── Уведомления (вызываются из workers) ──────────────────────────────────────
_bot_instance: Bot | None = None


async def notify_alert(tg_id: int, alert, snap, usd_rub: float):
    if not _bot_instance: return
    try:
        profit = round((snap.buff_price or 0) * snap.best_roi / 100, 2)
        await _bot_instance.send_message(
            tg_id,
            f"🔔 <b>Алерт сработал!</b>\n\n"
            f"<b>{snap.name}</b>\n"
            f"ROI: <b>{snap.best_roi:.1f}%</b> | +${profit:.2f}\n"
            f"Buff: ${snap.buff_price:.2f}",
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(f"notify_alert: {e}")


async def notify_unlock(tg_id: int, pos):
    if not _bot_instance: return
    try:
        await _bot_instance.send_message(
            tg_id,
            f"💼 <b>Позиция разморожена!</b>\n\n"
            f"<b>{pos.skin_name}</b> готова к продаже.\n"
            f"Куплено за ${pos.buy_price_usd:.2f}",
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(f"notify_unlock: {e}")


async def notify_buff_expiry(tg_id: int, age_days: int):
    if not _bot_instance: return
    try:
        await _bot_instance.send_message(
            tg_id,
            f"⚠️ <b>Buff сессия истекает!</b>\n\n"
            f"Куке уже {age_days} дней. Обнови через /buff",
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(f"notify_buff_expiry: {e}")


# ── Запуск ────────────────────────────────────────────────────────────────────
async def start_bot():
    global _bot_instance
    from config import get_settings
    settings = get_settings()
    bot = Bot(token=settings.BOT_TOKEN)
    _bot_instance = bot
    log.info("Telegram бот запущен")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])