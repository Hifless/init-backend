from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional

from database import (get_db, User, AccessKey, ArbitrageSnapshot,
                      PriceHistory, Alert, Position, Trade)
from auth import get_user_by_tg, is_owner, create_access_key, activate_key

# ── Shared dependency ─────────────────────────────────────────────────────────
async def current_user(tg_id: int, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_user_by_tg(db, tg_id)
    if not user or not user.access_key:
        raise HTTPException(403, "Нет доступа. Активируй ключ через /activate в боте")
    return user


# ===========================================================================
# USERS
# ===========================================================================
users = APIRouter()

class SettingsIn(BaseModel):
    usd_rub:        Optional[float] = None
    notify_tg:      Optional[bool]  = None
    notify_app:     Optional[bool]  = None
    min_roi_notify: Optional[float] = None

@users.get("/me")
async def get_me(tg_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_tg(db, tg_id)
    if not user:
        raise HTTPException(404, "Не найден")
    buff_age = None
    if user.buff_updated_at:
        buff_age = (datetime.utcnow() - user.buff_updated_at).days
    return {
        "tg_id":          user.tg_id,
        "username":       user.username,
        "role":           user.role,
        "has_access":     bool(user.access_key),
        "has_buff":       bool(user.buff_session),
        "buff_age_days":  buff_age,
        "buff_expiring":  buff_age is not None and buff_age >= 10,
        "usd_rub":        user.usd_rub,
        "cny_usd":        user.cny_usd,
        "notify_tg":      user.notify_tg,
        "notify_app":     user.notify_app,
        "min_roi_notify": user.min_roi_notify,
    }

@users.patch("/settings")
async def update_settings(tg_id: int, body: SettingsIn, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    if body.usd_rub        is not None: user.usd_rub        = body.usd_rub
    if body.notify_tg      is not None: user.notify_tg      = body.notify_tg
    if body.notify_app     is not None: user.notify_app     = body.notify_app
    if body.min_roi_notify is not None: user.min_roi_notify = body.min_roi_notify
    await db.commit()
    return {"ok": True}

@users.get("/keys")
async def list_keys(tg_id: int, db: AsyncSession = Depends(get_db)):
    if not await is_owner(db, tg_id):
        raise HTTPException(403, "Только для владельца")
    res = await db.execute(select(AccessKey).where(AccessKey.owner.has(User.tg_id == tg_id)))
    keys = res.scalars().all()
    return [{"key": k.key, "is_used": k.is_used, "used_by_tg": k.used_by_tg,
             "used_at": k.used_at, "created_at": k.created_at} for k in keys]

@users.post("/genkey")
async def gen_key(tg_id: int, db: AsyncSession = Depends(get_db)):
    if not await is_owner(db, tg_id):
        raise HTTPException(403, "Только для владельца")
    key = await create_access_key(db, tg_id)
    return {"key": key}

class ActivateIn(BaseModel):
    key: str

@users.post("/activate")
async def activate_key_endpoint(tg_id: int, body: ActivateIn, db: AsyncSession = Depends(get_db)):
    result = await activate_key(db, body.key.strip().upper(), tg_id, username="")
    if not result["ok"]:
        raise HTTPException(400, result["reason"])
    user = await get_user_by_tg(db, tg_id)
    return {"ok": True, "has_access": True}


# ===========================================================================
# ARBITRAGE
# ===========================================================================
arbitrage = APIRouter()

FEES = {"cgm": 0.07, "skinport": 0.12, "steam": 0.15}

@arbitrage.get("/list")
async def list_arb(tg_id: int, min_roi: float = 0, sort: str = "roi",
                   db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    res = await db.execute(
        select(ArbitrageSnapshot).where(ArbitrageSnapshot.best_roi >= min_roi)
    )
    snaps = res.scalars().all()

    items = []
    for s in snaps:
        platforms = {}
        for pkey, price in [("cgm", s.cgm_price), ("skinport", s.skinport_price), ("steam", s.steam_price)]:
            if not price: continue
            fee     = FEES.get(pkey, 0.07)
            net_usd = price * (1 - fee)
            profit  = net_usd - (s.buff_price or 0)
            roi     = profit / (s.buff_price or 1) * 100
            platforms[pkey] = {
                "label":      {"cgm": "CSGOMarket (-7%)", "skinport": "Skinport (-12%)", "steam": "Steam (-15%)"}[pkey],
                "sell_price": round(price, 2),
                "net_usd":    round(net_usd, 2),
                "net_rub":    round(net_usd * user.usd_rub, 0),
                "profit_usd": round(profit, 2),
                "profit_rub": round(profit * user.usd_rub, 0),
                "roi":        round(roi, 1),
            }
        liq = "high" if s.buff_sell_num > 50 else ("med" if s.buff_sell_num > 15 else "low")
        items.append({
            "name":         s.name,
            "icon_url":     s.icon_url,
            "buff_price":   s.buff_price,
            "buff_price_rub": round((s.buff_price or 0) * user.usd_rub, 0),
            "best_roi":     s.best_roi,
            "best_sell":    s.best_sell_platform,
            "sell_num":     s.buff_sell_num,
            "buy_num":      s.buff_buy_num,
            "liquidity":    liq,
            "platforms":    platforms,
            "updated_at":   s.updated_at.isoformat(),
        })

    if sort == "roi":   items.sort(key=lambda x: x["best_roi"], reverse=True)
    elif sort == "price": items.sort(key=lambda x: x["buff_price"] or 0)
    return items


# ===========================================================================
# CHARTS
# ===========================================================================
charts = APIRouter()

PERIOD_DAYS = {"1д": 1, "7д": 7, "30д": 30, "90д": 90}

@charts.get("/history")
async def get_history(tg_id: int, name: str, period: str = "7д",
                      db: AsyncSession = Depends(get_db)):
    await current_user(tg_id, db)
    since = datetime.utcnow() - timedelta(days=PERIOD_DAYS.get(period, 7))
    res = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.name == name, PriceHistory.recorded_at >= since)
        .order_by(PriceHistory.recorded_at)
    )
    rows = res.scalars().all()
    by_platform: dict = {}
    for r in rows:
        by_platform.setdefault(r.platform, []).append({"ts": r.recorded_at.isoformat(), "price": r.price_usd})
    return by_platform


# ===========================================================================
# ALERTS
# ===========================================================================
alerts = APIRouter()

class AlertIn(BaseModel):
    skin_name: str
    condition: str
    value:     Optional[float] = None
    platform:  str = "buff"

@alerts.get("/")
async def list_alerts(tg_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    res  = await db.execute(select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc()))
    return [{"id": a.id, "skin_name": a.skin_name, "condition": a.condition,
             "value": a.value, "active": a.active,
             "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
             "created_at": a.created_at.isoformat()} for a in res.scalars()]

@alerts.post("/")
async def create_alert(tg_id: int, body: AlertIn, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    a = Alert(user_id=user.id, skin_name=body.skin_name, condition=body.condition,
              value=body.value, platform=body.platform)
    db.add(a); await db.commit()
    return {"ok": True, "id": a.id}

@alerts.patch("/{alert_id}/toggle")
async def toggle_alert(tg_id: int, alert_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    res  = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    a    = res.scalar_one_or_none()
    if not a: raise HTTPException(404)
    a.active = not a.active; await db.commit()
    return {"ok": True, "active": a.active}

@alerts.delete("/{alert_id}")
async def delete_alert(tg_id: int, alert_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    await db.execute(delete(Alert).where(Alert.id == alert_id, Alert.user_id == user.id))
    await db.commit(); return {"ok": True}


# ===========================================================================
# PORTFOLIO
# ===========================================================================
portfolio = APIRouter()

class PositionIn(BaseModel):
    skin_name:     str
    quantity:      int = 1
    buy_price_usd: float
    buy_platform:  str = "buff"
    sell_platform: str = "cgm"
    icon_url:      Optional[str] = None
    notes:         Optional[str] = None

@portfolio.get("/")
async def list_portfolio(tg_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    res  = await db.execute(
        select(Position).where(Position.user_id == user.id, Position.status != "sold")
        .order_by(Position.bought_at.desc())
    )
    positions = res.scalars().all()
    frozen = sum(p.buy_price_usd * p.quantity for p in positions)
    return {
        "total_frozen_usd": round(frozen, 2),
        "total_frozen_rub": round(frozen * user.usd_rub, 0),
        "positions": [{
            "id":            p.id,
            "skin_name":     p.skin_name,
            "quantity":      p.quantity,
            "buy_price":     p.buy_price_usd,
            "buy_price_rub": round(p.buy_price_usd * user.usd_rub, 0),
            "buy_platform":  p.buy_platform,
            "sell_platform": p.sell_platform,
            "icon_url":      p.icon_url,
            "status":        p.status,
            "bought_at":     p.bought_at.isoformat(),
            "unlock_at":     p.unlock_at.isoformat() if p.unlock_at else None,
            "days_left":     max(0, (p.unlock_at - datetime.utcnow()).days) if p.unlock_at and p.status == "locked" else None,
            "notes":         p.notes,
        } for p in positions]
    }

@portfolio.post("/")
async def add_position(tg_id: int, body: PositionIn, db: AsyncSession = Depends(get_db)):
    user  = await current_user(tg_id, db)
    unlock = datetime.utcnow() + timedelta(days=14)
    p = Position(user_id=user.id, skin_name=body.skin_name, quantity=body.quantity,
                 buy_price_usd=body.buy_price_usd, buy_platform=body.buy_platform,
                 sell_platform=body.sell_platform, icon_url=body.icon_url,
                 notes=body.notes, unlock_at=unlock)
    db.add(p); await db.commit()
    return {"ok": True, "id": p.id, "unlock_at": unlock.isoformat()}

@portfolio.delete("/{pos_id}")
async def del_position(tg_id: int, pos_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    await db.execute(delete(Position).where(Position.id == pos_id, Position.user_id == user.id))
    await db.commit(); return {"ok": True}


# ===========================================================================
# TRADES
# ===========================================================================
trades = APIRouter()

TRADE_FEES = {"cgm": 0.07, "skinport": 0.12, "steam": 0.15, "csfloat": 0.02}

class TradeIn(BaseModel):
    skin_name:      str
    quantity:       int = 1
    buy_price_usd:  float
    sell_price_usd: Optional[float] = None
    buy_platform:   str = "buff"
    sell_platform:  Optional[str] = None
    icon_url:       Optional[str] = None
    bought_at:      Optional[str] = None
    sold_at:        Optional[str] = None

@trades.get("/")
async def list_trades(tg_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    res  = await db.execute(
        select(Trade).where(Trade.user_id == user.id).order_by(Trade.bought_at.desc()).limit(200)
    )
    all_trades = res.scalars().all()
    total_profit = sum((t.profit_usd or 0) for t in all_trades)
    total_spent  = sum(t.buy_price_usd * t.quantity for t in all_trades)
    closed       = [t for t in all_trades if t.roi_pct is not None]
    avg_roi      = sum(t.roi_pct for t in closed) / len(closed) if closed else 0
    best_trade   = max(all_trades, key=lambda t: t.profit_usd or 0) if all_trades else None
    return {
        "summary": {
            "total_trades":     len(all_trades),
            "total_spent_usd":  round(total_spent, 2),
            "total_profit_usd": round(total_profit, 2),
            "total_profit_rub": round(total_profit * user.usd_rub, 0),
            "avg_roi":          round(avg_roi, 1),
            "best_trade_name":  best_trade.skin_name if best_trade else None,
            "best_trade_profit": round(best_trade.profit_usd or 0, 2) if best_trade else None,
        },
        "trades": [{
            "id":           t.id,
            "skin_name":    t.skin_name,
            "quantity":     t.quantity,
            "buy_price":    t.buy_price_usd,
            "sell_price":   t.sell_price_usd,
            "buy_platform": t.buy_platform,
            "sell_platform": t.sell_platform,
            "profit_usd":   t.profit_usd,
            "profit_rub":   round((t.profit_usd or 0) * user.usd_rub, 0),
            "roi_pct":      t.roi_pct,
            "icon_url":     t.icon_url,
            "bought_at":    t.bought_at.isoformat(),
            "sold_at":      t.sold_at.isoformat() if t.sold_at else None,
        } for t in all_trades]
    }

@trades.post("/")
async def add_trade(tg_id: int, body: TradeIn, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    profit = roi = None
    if body.sell_price_usd and body.sell_platform:
        fee     = TRADE_FEES.get(body.sell_platform, 0.07)
        net     = body.sell_price_usd * (1 - fee)
        profit  = round((net - body.buy_price_usd) * body.quantity, 2)
        roi     = round(profit / (body.buy_price_usd * body.quantity) * 100, 1)
    t = Trade(
        user_id=user.id, skin_name=body.skin_name, quantity=body.quantity,
        buy_price_usd=body.buy_price_usd, sell_price_usd=body.sell_price_usd,
        buy_platform=body.buy_platform, sell_platform=body.sell_platform,
        profit_usd=profit, roi_pct=roi, icon_url=body.icon_url,
        bought_at=datetime.fromisoformat(body.bought_at) if body.bought_at else datetime.utcnow(),
        sold_at=datetime.fromisoformat(body.sold_at) if body.sold_at else None,
    )
    db.add(t); await db.commit()
    return {"ok": True, "profit_usd": profit, "roi_pct": roi}

@trades.delete("/{trade_id}")
async def del_trade(tg_id: int, trade_id: int, db: AsyncSession = Depends(get_db)):
    user = await current_user(tg_id, db)
    await db.execute(delete(Trade).where(Trade.id == trade_id, Trade.user_id == user.id))
    await db.commit(); return {"ok": True}
