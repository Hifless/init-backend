import secrets
import hashlib
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import AccessKey, User


def generate_key(prefix: str = "SK") -> str:
    raw = secrets.token_hex(6).upper()
    return f"{prefix}-{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


async def get_user_by_tg(db: AsyncSession, tg_id: int) -> User | None:
    result = await db.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def is_owner(db: AsyncSession, tg_id: int) -> bool:
    user = await get_user_by_tg(db, tg_id)
    return user is not None and user.role == "owner"


async def has_access(db: AsyncSession, tg_id: int) -> bool:
    user = await get_user_by_tg(db, tg_id)
    return user is not None and user.access_key is not None


async def create_access_key(db: AsyncSession, owner_tg_id: int) -> str:
    owner = await get_user_by_tg(db, owner_tg_id)
    if not owner:
        raise ValueError("Owner not found")
    key = generate_key("SK")
    ak = AccessKey(key=key, owner_id=owner.id)
    db.add(ak)
    await db.commit()
    return key


async def activate_key(db: AsyncSession, key: str, tg_id: int,
                       username: str = "") -> dict:
    result = await db.execute(select(AccessKey).where(AccessKey.key == key))
    ak = result.scalar_one_or_none()

    if not ak:
        return {"ok": False, "reason": "Ключ не найден"}
    if ak.is_used:
        return {"ok": False, "reason": "Ключ уже использован"}

    # Активируем ключ
    ak.is_used = True
    ak.used_by_tg = tg_id
    ak.used_at = datetime.utcnow()

    # Создаём или обновляем юзера
    user = await get_user_by_tg(db, tg_id)
    if not user:
        user = User(tg_id=tg_id, username=username, role="user", access_key=key)
        db.add(user)
    else:
        user.access_key = key

    await db.commit()
    return {"ok": True}


async def ensure_owner(db: AsyncSession, tg_id: int, username: str = "") -> tuple:
    """Создаёт owner-аккаунт если не существует. Возвращает (user, key_or_None)."""
    user = await get_user_by_tg(db, tg_id)
    if user:
        return user, None

    key = generate_key("OWNER")
    user = User(tg_id=tg_id, username=username, role="owner", access_key=key)
    db.add(user)
    ak = AccessKey(key=key, owner_id=None, is_used=True,
                   used_by_tg=tg_id, used_at=datetime.utcnow())
    db.add(ak)
    await db.commit()
    # Обновляем owner_id
    ak.owner_id = user.id
    await db.commit()
    return user, key