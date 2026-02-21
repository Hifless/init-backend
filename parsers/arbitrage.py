"""
Комиссии при продаже (платит продавец):
  CSGOMarket — 7%
  Skinport   — 12%
  Steam      — 15%
  CSFloat    — 2%
"""

FEES = {
    "cgm":      0.07,
    "skinport": 0.12,
    "steam":    0.15,
    "csfloat":  0.02,
}

LABELS = {
    "buff":     "Buff.163",
    "cgm":      "CSGOMarket",
    "skinport": "Skinport",
    "steam":    "Steam",
    "csfloat":  "CSFloat",
}


def calc_arbitrage(buy_price: float, market_prices: dict[str, float | None],
                   usd_rub: float = 90.0) -> dict:
    """
    buy_price      — цена покупки на Buff (USD)
    market_prices  — {"cgm": 45.0, "skinport": 43.0, ...}  None если нет данных
    """
    platforms = {}
    for platform, sell in market_prices.items():
        if not sell or sell <= 0:
            continue
        fee     = FEES.get(platform, 0.0)
        net     = sell * (1 - fee)
        profit  = net - buy_price
        roi     = profit / buy_price * 100 if buy_price > 0 else 0
        platforms[platform] = {
            "label":      LABELS.get(platform, platform),
            "sell_price": round(sell, 2),
            "net_usd":    round(net, 2),
            "net_rub":    round(net * usd_rub, 0),
            "profit_usd": round(profit, 2),
            "profit_rub": round(profit * usd_rub, 0),
            "roi":        round(roi, 1),
        }

    if not platforms:
        return {"platforms": {}, "best": None, "best_roi": 0.0, "best_profit_usd": 0.0}

    best = max(platforms, key=lambda k: platforms[k]["roi"])
    return {
        "platforms":       platforms,
        "best":            best,
        "best_roi":        platforms[best]["roi"],
        "best_profit_usd": platforms[best]["profit_usd"],
        "best_profit_rub": platforms[best]["profit_rub"],
    }


def liquidity_label(sell_num: int) -> str:
    if sell_num > 50: return "high"
    if sell_num > 15: return "med"
    return "low"
