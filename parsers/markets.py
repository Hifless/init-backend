import aiohttp
import asyncio
import logging
import time

log = logging.getLogger("parser.markets")

# ── Кэши ──────────────────────────────────────────────────────────────────────
_cgm_cache: dict[str, float] = {}
_cgm_ts:    float = 0

_sp_cache:  dict[str, float] = {}
_sp_ts:     float = 0

CACHE_TTL = 300  # 5 мин

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://skinport.com",
    "Referer": "https://skinport.com/",
}


# ── CSGOMarket ────────────────────────────────────────────────────────────────
async def fetch_cgm(session: aiohttp.ClientSession) -> dict[str, float]:
    global _cgm_cache, _cgm_ts
    if time.time() - _cgm_ts < CACHE_TTL and _cgm_cache:
        return _cgm_cache
    try:
        async with session.get(
            "https://market.csgo.com/api/v2/prices/USD.json",
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                prices = {
                    i["market_hash_name"]: float(i["price"])
                    for i in data.get("items", [])
                    if i.get("market_hash_name") and i.get("price")
                }
                _cgm_cache, _cgm_ts = prices, time.time()
                log.info(f"CSGOMarket: {len(prices)} позиций загружено")
                return prices
            log.warning(f"CSGOMarket HTTP {resp.status}")
    except Exception as e:
        log.warning(f"CSGOMarket: {e}")
    return _cgm_cache


# ── Skinport ──────────────────────────────────────────────────────────────────
async def fetch_skinport(session: aiohttp.ClientSession) -> dict[str, float]:
    global _sp_cache, _sp_ts
    if time.time() - _sp_ts < CACHE_TTL and _sp_cache:
        return _sp_cache
    try:
        async with session.get(
            "https://api.skinport.com/v1/items",
            params={"app_id": 730, "currency": "USD", "tradable": 0},
            headers=BROWSER_HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                prices = {
                    i["market_hash_name"]: float(i["min_price"])
                    for i in data
                    if i.get("market_hash_name") and i.get("min_price")
                }
                _sp_cache, _sp_ts = prices, time.time()
                log.info(f"Skinport: {len(prices)} позиций загружено")
                return prices
            log.warning(f"Skinport HTTP {resp.status}")
    except Exception as e:
        log.warning(f"Skinport: {e}")
    return _sp_cache


# ── Steam (поштучно, осторожно с rate limit) ──────────────────────────────────
async def fetch_steam_price(session: aiohttp.ClientSession, name: str) -> float | None:
    try:
        async with session.get(
            "https://steamcommunity.com/market/priceoverview/",
            params={"appid": 730, "currency": 1, "market_hash_name": name},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                d = await resp.json()
                if d.get("success"):
                    raw = d.get("lowest_price", "").replace("$", "").replace(",", "").strip()
                    return float(raw) if raw else None
            elif resp.status == 429:
                await asyncio.sleep(5)
    except Exception:
        pass
    return None


# ── Арбитраж калькулятор ──────────────────────────────────────────────────────
FEES = {
    "cgm":      0.07,
    "skinport": 0.12,
    "steam":    0.15,
}

def calc_arbitrage(buy_price: float, market_prices: dict) -> dict:
    results = {}
    labels = {"cgm": "CSGOMarket (-7%)", "skinport": "Skinport (-12%)", "steam": "Steam (-15%)"}

    for platform, price in market_prices.items():
        if not price:
            continue
        fee    = FEES.get(platform, 0.1)
        sell   = round(price * (1 - fee), 2)
        profit = round(sell - buy_price, 2)
        roi    = round(profit / buy_price * 100, 1) if buy_price > 0 else 0
        results[platform] = {
            "label":  labels.get(platform, platform),
            "price":  price,
            "sell":   sell,
            "profit": profit,
            "roi":    roi,
        }

    best = max(results, key=lambda k: results[k]["roi"]) if results else None
    best_roi = results[best]["roi"] if best else 0

    return {
        "platforms":     results,
        "best_platform": best,
        "best_roi":      best_roi,
    }