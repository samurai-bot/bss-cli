"""SSE stream for the agent log widget. Filled in at Step 5."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/agent/events/{session_id}")
async def agent_events(session_id: str) -> dict:
    return {"sse": "scaffold — Step 5 replaces with streaming response"}
