from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.replay import replay_window

router = APIRouter(tags=["replay"])


class ReplayRequest(BaseModel):
    watchlist_id: UUID
    from_ts: datetime
    to_ts: datetime


@router.post("/replay")
async def post_replay(
    req: ReplayRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await replay_window(
        watchlist_id=req.watchlist_id,
        from_ts=req.from_ts,
        to_ts=req.to_ts,
        session=session,
    )
