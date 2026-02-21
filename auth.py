import secrets
import hashlib
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import AccessKey, User


def generate_key(prefix: str = "SK") -> str:
    """Генерирует уникальный ключ доступа. SK-XXXX-XXXX-XXXX"""
    raw = secrets.token_hex(6).upper()
    return f"{prefix}-{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


async def create_key(db: AsyncSession, note: str = "", permanent: bool = False) -> str:
    key = generate_key()
    db.add(AccessKey(key=key, note=note, is_permanent=permanent))
    await db.commit()
    return key


async def activate_key(db: AsyncSession, key: str, tg_id: int,
                        username: str = "", first_name: str = "") -> dict:
    """
    Активирует ключ для пользователя.
    Возвращает {"ok": True} или {"ok": False, "reason": "..."}
    """
    # Проверяем ключ
    result = await db.execute(select(AccessKey).where(AccessKey.key == key))
    ak = result.scalar_one_or_none()

    if not ak:
        return {"ok": False, "reason": "Ключ не найден"}

    if ak.is_used and not ak.is_permanent:
        return {"ok": False, "reason": "Ключ уже использован"}

    # Проверяем — не зарегистрирован ли юзер уже
    result2 = await db.execute(select(User).where(User.tg_id == tg_id))
    user = result2.scalar_one_or_none()

    if user:
        if user.is_active:
            return {"ok": True, "already": True}  # уже активирован
        else:
            user.is_active = True
            await db.commit()
            return {"ok": True}

    # Создаём нового пользователя
    new_user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        access_key=key,
        is_active=True,
    )
    db.add(new_user)

    # Помечаем ключ как использованный (если не permanent)
    if not ak.is_permanent:
        ak.is_used = True
        ak.used_by_tg = tg_id
        ak.used_at = datetime.utcnow()

    await db.commit()
    return {"ok": True}


async def get_user_by_tg(db: AsyncSession, tg_id: int) -> User | None:
    result = await db.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def verify_tg_auth(tg_id: int, db: AsyncSession) -> User | None:
    """Проверяет что пользователь активирован."""
    user = await get_user_by_tg(db, tg_id)
    if user and user.is_active:
        return user
    return None
