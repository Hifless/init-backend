import aiohttp
import asyncio
import logging
import time

log = logging.getLogger("parser.buff")


async def fetch_buff_page(session: aiohttp.ClientSession, buff_session: str,
                           page: int, cny_usd: float,
                           category: str = "knife") -> list[dict]:
    """
    Грузит страницу товаров с Buff.
    category: knife | rifle | pistol | '' (пустая = все)
    """
    url = "https://buff.163.com/api/market/goods"
    params = {
        "game": "csgo",
        "page_num": page,
        "page_size": 50,
        "sort_by": "price.asc",
    }
    if category:
        params["category_group"] = category

    headers = {
        "Cookie": f"session={buff_session}",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://buff.163.com/market/csgo",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                code = data.get("code", "")

                if code != "OK":
                    msg = str(data.get("error", code))
                    if "login" in msg.lower() or code in ("Login", "NotLogin"):
                        log.error("BUFF_SESSION протух — нужно обновить!")
                        return [{"_session_expired": True}]
                    log.warning(f"Buff API: {msg}")
                    return []

                items = data.get("data", {}).get("items", [])
                result = []

                for item in items:
                    try:
                        price_cny = float(item.get("sell_min_price", 0) or 0)
                        if price_cny <= 0:
                            continue

                        price_usd = round(price_cny * cny_usd, 2)
                        goods_id  = str(item.get("id", ""))
                        name      = item.get("market_hash_name", "")
                        goods_info = item.get("goods_info", {}) or {}
                        icon_path  = goods_info.get("icon_url", "")

                        # Сохраняем raw path — CDN подставляется через прокси
                        steam_img = None
                        if icon_path:
                            steam_img = f"/api/img?p={icon_path}"

                        steam_cny = float(goods_info.get("steam_price", 0) or 0)

                        result.append({
                            "id":        goods_id,
                            "name":      name,
                            "price_cny": price_cny,
                            "price_usd": price_usd,
                            "sell_num":  int(item.get("sell_num", 0) or 0),
                            "buy_num":   int(item.get("buy_num", 0) or 0),
                            "steam_usd": round(steam_cny * cny_usd, 2) if steam_cny > 0 else None,
                            "icon_url":  steam_img,
                            "buff_url":  f"https://buff.163.com/goods/{goods_id}",
                        })
                    except Exception:
                        continue

                return result

            elif resp.status == 429:
                log.warning("Buff rate limit — ждём 60с")
                await asyncio.sleep(60)
            elif resp.status in (401, 403):
                log.error("Buff: доступ запрещён (сессия?)")
                return [{"_session_expired": True}]
            else:
                log.error(f"Buff HTTP {resp.status}")

    except asyncio.TimeoutError:
        log.warning("Buff: таймаут запроса")
    except Exception as e:
        log.error(f"Buff ошибка: {e}")

    return []


async def fetch_cny_usd_rate(session: aiohttp.ClientSession) -> float:
    """Актуальный курс CNY/USD."""
    try:
        async with session.get(
            "https://open.er-api.com/v6/latest/CNY",
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                rate = data.get("rates", {}).get("USD")
                if rate:
                    log.info(f"Курс CNY/USD обновлён: {rate:.4f}")
                    return float(rate)
    except Exception as e:
        log.warning(f"Курс CNY/USD: {e}")
    return 0.138  # fallback