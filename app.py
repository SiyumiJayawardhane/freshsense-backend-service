import asyncio
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
 
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
 
import state
from config import (
    DEFAULT_USER_ID,
    EDGE_TRIGGER_TIMEOUT_SECONDS,
    EDGE_TRIGGER_TOKEN,
    EDGE_TRIGGER_URL,
    FRONTEND_ORIGIN,
    logger,
)
from db import get_conn
from email_worker import email_dispatch_worker
from ingestion import derive_detection, insert_notification, insert_sensor_reading, upsert_food_item
from schemas import EdgeTriggerRequest, IngestPayload
 
app = FastAPI(title="FreshSense Live Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 
async def broadcast(user_id: str, payload: dict[str, Any]) -> None:
    invalid_queues: list[asyncio.Queue] = []
    for queue in state.subscribers[user_id]:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            invalid_queues.append(queue)
    if invalid_queues:
        state.subscribers[user_id] = [q for q in state.subscribers[user_id] if q not in invalid_queues]
 
 
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
 
 
@app.on_event("startup")
async def on_startup() -> None:
    if state.email_worker_task is None:
        state.email_worker_task = asyncio.create_task(email_dispatch_worker())
 
 
@app.on_event("shutdown")
async def on_shutdown() -> None:
    if state.email_worker_task:
        state.email_worker_task.cancel()
        try:
            await state.email_worker_task
        except asyncio.CancelledError:
            pass
        state.email_worker_task = None
 
 
@app.get("/api/dashboard/{user_id}/latest")
def latest(user_id: str) -> dict[str, Any]:
    return state.latest_by_user.get(
        user_id,
        {"user_id": user_id, "latest_reading": None, "items": [], "updated_at": None},
    )
 
 
@app.get("/api/stream/{user_id}")
async def stream(user_id: str):
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    state.subscribers[user_id].append(queue)
 
    async def generator():
        try:
            initial = state.latest_by_user.get(user_id)
            if initial:
                yield f"data: {json.dumps({'type': 'snapshot', 'payload': initial})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps({'type': 'ingestion_update', 'payload': event})}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in state.subscribers[user_id]:
                state.subscribers[user_id].remove(queue)
 
    return StreamingResponse(generator(), media_type="text/event-stream")
 
 
@app.post("/api/ingest")
async def ingest(payload: IngestPayload):
    user_id = (payload.user_id or DEFAULT_USER_ID).strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id missing in payload and SUPABASE_USER_ID not set")
 
    now_iso = payload.captured_at or datetime.now(timezone.utc).isoformat()
    saved_items: list[dict[str, Any]] = []
 
    conn = get_conn()
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if not payload.detected_items:
                insert_sensor_reading(cur, user_id, None, payload.sensor, now_iso)
            else:
                for item in payload.detected_items:
                    detection = derive_detection(item)
                    food_item_id = upsert_food_item(cur, user_id, detection, now_iso)
                    insert_sensor_reading(cur, user_id, food_item_id, payload.sensor, now_iso)
 
                    if detection["freshness_status"] == "spoiled":
                        insert_notification(
                            cur,
                            user_id,
                            food_item_id,
                            f"[SPOILED] {detection['name']}",
                            f"{detection['name']} appears spoiled. Please discard it.",
                            "critical",
                            now_iso,
                        )
                    elif detection["freshness_status"] == "at_risk":
                        insert_notification(
                            cur,
                            user_id,
                            food_item_id,
                            f"[WARNING] {detection['name']} expiring soon",
                            f"Use {detection['name']} soon to avoid spoilage.",
                            "warning",
                            now_iso,
                        )
 
                    saved_items.append(
                        {
                            "name": detection["name"],
                            "freshness_status": detection["freshness_status"],
                            "confidence": detection["confidence"],
                            "food_item_id": food_item_id,
                        }
                    )
        conn.commit()
    except Exception as ex:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"ingest failed: {ex}") from ex
    finally:
        conn.close()
 
    snapshot = {
        "user_id": user_id,
        "latest_reading": {
            "humidity": payload.sensor.humidity,
            "temperature": payload.sensor.temperature,
            "gas_value": payload.sensor.gas_value,
            "recorded_at": now_iso,
        },
        "items": saved_items,
        "updated_at": now_iso,
    }
    state.latest_by_user[user_id] = snapshot
    await broadcast(user_id, snapshot)
    return {"ok": True, "saved_items": len(saved_items)}
 
 
@app.post("/api/edge/trigger")
async def trigger_edge(payload: EdgeTriggerRequest):
    if not EDGE_TRIGGER_URL:
        logger.warning("Edge trigger requested but EDGE_TRIGGER_URL is missing")
        raise HTTPException(status_code=503, detail="EDGE_TRIGGER_URL is not configured")
 
    source = payload.source or "live-backend"
    trigger_url = f"{EDGE_TRIGGER_URL.rstrip('/')}/trigger-run"
    request_body = json.dumps({"source": source}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if EDGE_TRIGGER_TOKEN:
        headers["X-Edge-Trigger-Token"] = EDGE_TRIGGER_TOKEN
 
    logger.info("Forwarding manual trigger to edge source=%s url=%s", source, trigger_url)
    req = urllib.request.Request(trigger_url, data=request_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=EDGE_TRIGGER_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8") if resp.length != 0 else "{}"
            data = json.loads(raw or "{}")
            logger.info("Edge trigger accepted status=%s source=%s", getattr(resp, "status", "unknown"), source)
            return {"ok": True, "edge_response": data}
    except urllib.error.HTTPError as ex:
        err_body = ex.read().decode("utf-8", errors="ignore")
        logger.error("Edge trigger HTTP error status=%s source=%s body=%s", ex.code, source, err_body)
        raise HTTPException(status_code=502, detail=f"edge trigger failed: {ex.code} {err_body}") from ex
    except urllib.error.URLError as ex:
        logger.error("Edge trigger connection error source=%s reason=%s", source, ex.reason)
        raise HTTPException(status_code=502, detail=f"edge trigger connection failed: {ex.reason}") from ex
 
 
if __name__ == "__main__":
    import uvicorn
 
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=False)