import json

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from genesis.bus import SubtitleBus
from genesis.models import validate_session_id


async def stream_subtitles(session_id: str, bus: SubtitleBus) -> StreamingResponse:
    try:
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def events():
        async for event in bus.subscribe(session_id):
            payload = json.dumps(event.model_dump(), ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
