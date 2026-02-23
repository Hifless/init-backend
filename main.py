from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
import os
import aiohttp

from database import init_db, AsyncSessionLocal
from routers.routes import users, arbitrage, charts, alerts, portfolio, trades
from workers import start_workers
from bot.bot import start_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("skintel")

# Steam CDN варианты (пробуем по порядку)
STEAM_CDNS = [
    "https://steamcommunity-a.akamaihd.net/economy/image",
    "https://community.cloudflare.steamstatic.com/economy/image",
    "https://cdn.steam.tools/images/economy/image",
]

_img_session: aiohttp.ClientSession | None = None

async def get_img_session():
    global _img_session
    if _img_session is None or _img_session.closed:
        _img_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    return _img_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("✅ БД инициализирована")

    owner_tg_id = int(os.getenv("OWNER_TG_ID", "0"))
    if owner_tg_id:
        from auth import ensure_owner
        async with AsyncSessionLocal() as db:
            user, key = await ensure_owner(db, owner_tg_id, "owner")
            if key:
                log.info(f"🔑 OWNER KEY: {key}")
            else:
                log.info("👑 Owner уже существует")

    asyncio.create_task(start_workers())
    asyncio.create_task(start_bot())
    log.info("✅ Воркеры и бот запущены")
    yield
    if _img_session and not _img_session.closed:
        await _img_session.close()
    log.info("🛑 Завершение")


app = FastAPI(title="SKINTEL API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users,     prefix="/api/users",     tags=["users"])
app.include_router(arbitrage, prefix="/api/arbitrage", tags=["arbitrage"])
app.include_router(charts,    prefix="/api/charts",    tags=["charts"])
app.include_router(alerts,    prefix="/api/alerts",    tags=["alerts"])
app.include_router(portfolio, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(trades,    prefix="/api/trades",    tags=["trades"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/img")
async def proxy_image(p: str):
    """Прокси для Steam CDN картинок — обходит блокировку Telegram WebApp."""
    if not p or len(p) > 500:
        return Response(status_code=400)
    # Убираем слэши по краям
    p = p.strip("/")

    session = await get_img_session()
    for cdn in STEAM_CDNS:
        url = f"{cdn}/{p}/96fx96f"
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status == 200:
                    content = await r.read()
                    ct = r.headers.get("Content-Type", "image/png")
                    return Response(
                        content=content,
                        media_type=ct,
                        headers={
                            "Cache-Control": "public, max-age=86400",
                            "Access-Control-Allow-Origin": "*",
                        }
                    )
        except Exception:
            continue

    return Response(status_code=404)