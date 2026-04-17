"""AI Caller Service — FastAPI backend"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from .models import CallCreate, CallResponse, CallStatus
from .db import init_db, create_call, get_call, update_call, list_calls
from .voice_engine import build_system_prompt, transcribe, think, synthesize, generate_report
from .call_manager import CallSession
from .config import SERVER_HOST, SERVER_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("ai-caller")

# Active call sessions
active_sessions: dict[str, CallSession] = {}
# WebSocket connections per call
ws_connections: dict[str, list[WebSocket]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("AI Caller Service started")
    yield
    # Cleanup active sessions
    for session in active_sessions.values():
        await session.close()
    log.info("AI Caller Service stopped")


app = FastAPI(title="AI Caller Service", version="0.1.0", lifespan=lifespan)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


# --- API Endpoints ---

@app.post("/api/calls", response_model=CallResponse)
async def create_call_endpoint(data: CallCreate):
    call_data = create_call(data.model_dump())
    call_id = call_data["id"]
    log.info(f"Call created: {call_id} -> {data.phone}")

    # Start call in background
    asyncio.create_task(run_call(call_id, data))

    return CallResponse(**call_data)


@app.get("/api/calls", response_model=list[CallResponse])
async def list_calls_endpoint():
    calls = list_calls()
    return [CallResponse(**c) for c in calls]


@app.get("/api/calls/{call_id}", response_model=CallResponse)
async def get_call_endpoint(call_id: str):
    call = get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return CallResponse(**call)


@app.get("/api/calls/{call_id}/transcript")
async def get_transcript(call_id: str):
    call = get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return {"transcript": call.get("transcript", ""), "report": call.get("report", "")}


@app.websocket("/ws/calls/{call_id}")
async def call_websocket(websocket: WebSocket, call_id: str):
    await websocket.accept()
    if call_id not in ws_connections:
        ws_connections[call_id] = []
    ws_connections[call_id].append(websocket)
    try:
        # Send current state
        call = get_call(call_id)
        if call:
            await websocket.send_json({"type": "status", "status": call["status"]})

        while True:
            data = await websocket.receive_text()
            # Client can send commands like stop
            msg = json.loads(data)
            if msg.get("action") == "stop":
                session = active_sessions.get(call_id)
                if session:
                    await session.hangup()
    except WebSocketDisconnect:
        ws_connections.get(call_id, []).remove(websocket) if websocket in ws_connections.get(call_id, []) else None


async def broadcast_ws(call_id: str, message: dict):
    """Send message to all WebSocket clients for a call"""
    for ws in ws_connections.get(call_id, []):
        try:
            await ws.send_json(message)
        except Exception:
            pass


async def run_call(call_id: str, data: CallCreate):
    """Main call orchestration loop"""
    log.info(f"Starting call {call_id} to {data.phone}")

    system_prompt = build_system_prompt(
        task=data.task,
        language=data.language,
        caller_name=data.caller_name,
        required_info=data.required_info,
        restrictions=data.restrictions,
    )

    session = CallSession(call_id, data.phone, system_prompt)
    active_sessions[call_id] = session

    update_call(call_id, {"status": "dialing"})
    await broadcast_ws(call_id, {"type": "status", "status": "dialing"})

    # Try to originate call
    success = await session.originate()
    if not success:
        update_call(call_id, {"status": "failed"})
        await broadcast_ws(call_id, {
            "type": "status", "status": "failed",
            "reason": "Could not originate call"
        })
        await session.close()
        del active_sessions[call_id]
        return

    update_call(call_id, {"status": "in_progress"})
    await broadcast_ws(call_id, {"type": "status", "status": "in_progress"})

    # Start recording
    rec_path = await session.record_start()

    # Generate and play initial greeting
    greeting = await think(system_prompt, session.conversation,
                          "Звонок начался. Поприветствуй и представься.")
    session.add_transcript("assistant", greeting)
    await broadcast_ws(call_id, {
        "type": "transcript", "role": "assistant", "text": greeting
    })

    greeting_audio = await synthesize(greeting)
    if greeting_audio:
        await session.play_audio(greeting_audio)

    # Wait for the greeting to play, then wait for response
    # In a full implementation, we'd have a real-time audio stream
    # For MVP, we'll use a simplified turn-based approach with recording chunks
    await asyncio.sleep(5)  # Wait for greeting to play

    # Simplified: for MVP, the call plays greeting and records
    # Full duplex audio processing would require mod_shout or similar
    # For now, we'll simulate a reasonable call flow

    # Record for a set time and process
    max_turns = 10
    for turn in range(max_turns):
        # Wait for speech (simplified - in production use VAD)
        await asyncio.sleep(8)

        # Check if call is still active
        status_check = await session.esl.api(f"uuid_exists {call_id}")
        if "true" not in status_check.lower():
            log.info(f"Call {call_id} ended by remote party")
            break

        # In production: read audio chunk from recording, send to STT
        # For MVP: the recording captures everything, we'll process after
        log.info(f"Turn {turn+1} - call still active")

    # End call
    await session.hangup()
    duration = session.duration

    update_call(call_id, {
        "status": "completed",
        "duration_seconds": duration,
        "completed_at": datetime.now(timezone.utc).isoformat()
    })

    # Process full recording for transcript (post-call)
    try:
        import os
        if os.path.exists(rec_path):
            with open(rec_path, "rb") as f:
                audio_data = f.read()
            if audio_data:
                full_text = await transcribe(audio_data, "recording.wav")
                if full_text:
                    update_call(call_id, {"transcript": full_text})
                    report = await generate_report(data.task, full_text)
                    update_call(call_id, {"report": report})
                    await broadcast_ws(call_id, {
                        "type": "completed",
                        "transcript": full_text,
                        "report": report,
                        "duration": duration
                    })
    except Exception as e:
        log.error(f"Post-call processing error: {e}")

    await broadcast_ws(call_id, {"type": "status", "status": "completed"})

    # Cleanup
    await session.close()
    if call_id in active_sessions:
        del active_sessions[call_id]


# Health check
@app.get("/api/health")
async def health():
    from .call_manager import ESLClient
    esl = ESLClient()
    fs_ok = await esl.connect()
    await esl.close()
    return {
        "status": "ok",
        "freeswitch": "connected" if fs_ok else "disconnected",
        "active_calls": len(active_sessions)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
