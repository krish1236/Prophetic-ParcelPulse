from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.health import source_status
from parcelpulse.registry import all_adapters
from parcelpulse.routes import parcels
from parcelpulse.settings import settings

app = FastAPI(title="ParcelPulse", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(parcels.router)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    return {
        "status": "ok",
        "sources": await source_status(all_adapters(), session),
    }
