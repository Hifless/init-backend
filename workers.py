import asyncio
import logging
import time
from datetime import datetime, timedelta

import aiohttp
from sqlalchemy import select

from database import (AsyncSessionLocal, ArbitrageSnapshot, PriceHistory,
                      Alert, User, Position)
from parsers.buff import fetch_buff_page, fetch_cny_usd_rate
from parsers.markets import fetch_cgm, fetch_skinport
from parsers.arbitrage import calc_arbitrage, liquidity_label

log = logging.getLogger("workers")

_cny_usd: float = 0.138
_cny_updated: float = 0.0


async def _update_rate(session: aiohttp.ClientSession):
    global _cny_usd, _cny_updated
    if time.time() - _cny_updated > 3600:
        rate = await fetch_cny_usd_rate(session)
        if rate:
            _cny_usd = rate
            _cny_updated = time.time()
            log.info(f"CNY/USD = {_cny_usd:.4f}")


async def price_collector():
    """Каждые 5 минут: парсит Buff + CGM + Skinport, пишет историю цен."""
    log.info("📊 price_collector started")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await _update_rate(session)
                cgm_prices = await fetch_cgm(session)
                sp_prices  = await fetch_skinport(session)

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(User).where(User.buff_session.isnot(None)).limit(1)
                    )
                    u = result.scalar_one_or_none()

                if not u:
                    log.warning("Нет пользователей с Buff сессией — пропускаем")
                    await asyncio.sleep(300)
                    continue

                all_items: list[dict] = []
                for page in range(1, 5):
                    items = await fetch_buff_page(session, u.buff_session, page, _cny_usd)
                    if not items:
                        break
                    all_items.extend(items)
                    await asyncio.sleep(2)

                log.info(f"Buff: {len(all_items)} позиций")
                now = datetime.utcnow()
                history_rows: list = []

                async with AsyncSessionLocal() as db:
                    for item in all_items:
                        name = item["name"]
                        buff_usd = item["price_usd"]
                        cgm_usd  = cgm_prices.get(name)
                        sp_usd   = sp_prices.get(name)

                        markets = {}
                        if cgm_usd: markets["cgm"]     = cgm_usd
                        if sp_usd:  markets["skinport"] = sp_usd

                        arb = calc_arbitrage(buff_usd, markets, u.usd_rub)

                        res = await db.execute(
                            select(ArbitrageSnapshot).where(ArbitrageSnapshot.name == name)
                        )
                        snap = res.scalar_one_or_none()
                        data = dict(
                            icon_url=item["icon_url"], buff_price=buff_usd,
                            cgm_price=cgm_usd, skinport_price=sp_usd,
                            buff_sell_num=item["sell_num"], buff_buy_num=item["buy_num"],
                            best_roi=arb["best_roi"], best_sell_platform=arb["best"],
                            updated_at=now,
                        )
                        if snap:
                            for k, v in data.items(): setattr(snap, k, v)
                        else:
                            db.add(ArbitrageSnapshot(name=name, **data))

                        history_rows.append(PriceHistory(name=name, platform="buff",     price_usd=buff_usd, recorded_at=now))
                        if cgm_usd: history_rows.append(PriceHistory(name=name, platform="cgm",      price_usd=cgm_usd, recorded_at=now))
                        if sp_usd:  history_rows.append(PriceHistory(name=name, platform="skinport", price_usd=sp_usd,  recorded_at=now))

                    db.add_all(history_rows)
                    await db.commit()
                    log.info(f"✅ {len(all_items)} снапшотов, {len(history_rows)} точек истории")

            except Exception as e:
                log.error(f"price_collector: {e}", exc_info=True)

            await asyncio.sleep(300)


async def alert_checker():
    """Каждую минуту проверяет алерты."""
    log.info("🔔 alert_checker started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Alert, User, ArbitrageSnapshot)
                    .join(User, Alert.user_id == User.id)
                    .join(ArbitrageSnapshot, Alert.skin_name == ArbitrageSnapshot.name, isouter=True)
                    .where(Alert.active == True)
                )
                rows = result.all()

            for alert, user, snap in rows:
                if not snap: continue
                triggered = False
                if   alert.condition == "roi_gt"   and alert.value: triggered = snap.best_roi >= alert.value
                elif alert.condition == "price_lt" and alert.value: triggered = 0 < (snap.buff_price or 0) <= alert.value
                elif alert.condition == "appeared":                 triggered = snap.buff_price is not None

                if triggered:
                    async with AsyncSessionLocal() as db2:
                        res2 = await db2.execute(select(Alert).where(Alert.id == alert.id))
                        a2 = res2.scalar_one_or_none()
                        if a2: a2.triggered_at = datetime.utcnow(); await db2.commit()
                    if user.notify_tg:
                        from bot.bot import notify_alert
                        await notify_alert(user.tg_id, alert, snap, user.usd_rub)
        except Exception as e:
            log.error(f"alert_checker: {e}")
        await asyncio.sleep(60)


async def portfolio_checker():
    """Каждый час проверяет разморозку позиций."""
    log.info("💼 portfolio_checker started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Position, User).join(User, Position.user_id == User.id)
                    .where(Position.status == "locked")
                    .where(Position.unlock_at <= datetime.utcnow())
                )
                rows = result.all()
                for pos, user in rows:
                    pos.status = "ready"
                    if user.notify_tg:
                        from bot.bot import notify_unlock
                        await notify_unlock(user.tg_id, pos)
                if rows: await db.commit(); log.info(f"💼 Разморожено {len(rows)} позиций")
        except Exception as e:
            log.error(f"portfolio_checker: {e}")
        await asyncio.sleep(3600)


async def buff_cookie_checker():
    """Раз в сутки предупреждает об истечении Buff куки."""
    log.info("🍪 buff_cookie_checker started")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.buff_session.isnot(None)))
                users = result.scalars().all()
                for user in users:
                    if not user.buff_updated_at: continue
                    age = (datetime.utcnow() - user.buff_updated_at).days
                    if age >= 10:
                        from bot.bot import notify_buff_expiry
                        await notify_buff_expiry(user.tg_id, age)
        except Exception as e:
            log.error(f"buff_cookie_checker: {e}")
        await asyncio.sleep(86400)


async def start_workers():
    await asyncio.gather(
        price_collector(),
        alert_checker(),
        portfolio_checker(),
        buff_cookie_checker(),
    )
