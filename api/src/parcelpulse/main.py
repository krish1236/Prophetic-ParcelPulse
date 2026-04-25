from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
async def health() -> dict[str, str]:
    return {"status": "ok"}
