from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from typing import Optional
from config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=settings.DEBUG,
    pool_size=5, max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id:           Mapped[int]  = mapped_column(primary_key=True)
    tg_id:        Mapped[int]  = mapped_column(Integer, unique=True, index=True)
    username:     Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role:         Mapped[str]  = mapped_column(String(20), default="user")  # owner / user
    access_key:   Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    buff_session: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    buff_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    usd_rub:      Mapped[float] = mapped_column(Float, default=90.0)
    cny_usd:      Mapped[float] = mapped_column(Float, default=0.138)
    notify_tg:    Mapped[bool]  = mapped_column(Boolean, default=True)
    notify_app:   Mapped[bool]  = mapped_column(Boolean, default=True)
    min_roi_notify: Mapped[float] = mapped_column(Float, default=10.0)
    created_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    alerts:    Mapped[list["Alert"]]    = relationship(back_populates="user", cascade="all, delete")
    positions: Mapped[list["Position"]] = relationship(back_populates="user", cascade="all, delete")
    trades:    Mapped[list["Trade"]]    = relationship(back_populates="user", cascade="all, delete")
    keys:      Mapped[list["AccessKey"]] = relationship(back_populates="owner", cascade="all, delete")


class AccessKey(Base):
    __tablename__ = "access_keys"
    id:         Mapped[int]  = mapped_column(primary_key=True)
    key:        Mapped[str]  = mapped_column(String(64), unique=True, index=True)
    owner_id:   Mapped[int]  = mapped_column(ForeignKey("users.id"))
    used_by_tg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_used:    Mapped[bool] = mapped_column(Boolean, default=False)
    used_at:    Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    owner: Mapped["User"] = relationship(back_populates="keys")


class PriceHistory(Base):
    __tablename__ = "price_history"
    id:          Mapped[int]   = mapped_column(primary_key=True)
    name:        Mapped[str]   = mapped_column(String(200), index=True)
    platform:    Mapped[str]   = mapped_column(String(30))
    price_usd:   Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ArbitrageSnapshot(Base):
    __tablename__ = "arbitrage_snapshots"
    id:           Mapped[int]   = mapped_column(primary_key=True)
    name:         Mapped[str]   = mapped_column(String(200), unique=True, index=True)
    icon_url:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    buff_price:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cgm_price:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    skinport_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    steam_price:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buff_sell_num: Mapped[int]  = mapped_column(Integer, default=0)
    buff_buy_num:  Mapped[int]  = mapped_column(Integer, default=0)
    best_roi:     Mapped[float] = mapped_column(Float, default=0.0)
    best_sell_platform: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    updated_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id:          Mapped[int]  = mapped_column(primary_key=True)
    user_id:     Mapped[int]  = mapped_column(ForeignKey("users.id"))
    skin_name:   Mapped[str]  = mapped_column(String(200))
    condition:   Mapped[str]  = mapped_column(String(50))   # roi_gt / price_lt / appeared
    value:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    platform:    Mapped[str]  = mapped_column(String(30), default="buff")
    active:      Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["User"] = relationship(back_populates="alerts")


class Position(Base):
    __tablename__ = "portfolio"
    id:           Mapped[int]   = mapped_column(primary_key=True)
    user_id:      Mapped[int]   = mapped_column(ForeignKey("users.id"))
    skin_name:    Mapped[str]   = mapped_column(String(200))
    quantity:     Mapped[int]   = mapped_column(Integer, default=1)
    buy_price_usd: Mapped[float] = mapped_column(Float)
    buy_platform:  Mapped[str]  = mapped_column(String(30), default="buff")
    sell_platform: Mapped[str]  = mapped_column(String(30), default="cgm")
    icon_url:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bought_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unlock_at:    Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status:       Mapped[str]   = mapped_column(String(20), default="locked")
    notes:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user: Mapped["User"] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"
    id:            Mapped[int]   = mapped_column(primary_key=True)
    user_id:       Mapped[int]   = mapped_column(ForeignKey("users.id"))
    skin_name:     Mapped[str]   = mapped_column(String(200))
    quantity:      Mapped[int]   = mapped_column(Integer, default=1)
    buy_price_usd: Mapped[float] = mapped_column(Float)
    sell_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buy_platform:  Mapped[str]   = mapped_column(String(30))
    sell_platform: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    profit_usd:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roi_pct:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    icon_url:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bought_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sold_at:       Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user: Mapped["User"] = relationship(back_populates="trades")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
