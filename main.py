from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging

from database import init_db
from routers.routes import users, arbitrage, charts, alerts, portfolio, trades
from workers import start_workers
from bot.bot import start_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("skintel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("✅ БД инициализирована")
    asyncio.create_task(start_workers())
    asyncio.create_task(start_bot())
    log.info("✅ Воркеры и бот запущены")
    yield
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
