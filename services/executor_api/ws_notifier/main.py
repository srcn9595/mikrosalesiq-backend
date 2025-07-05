from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import logging
from ws_notifier.redis_listener import start_redis_listener, active_connections

app = FastAPI()
log = logging.getLogger("ws_server")

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    active_connections[user_id] = websocket
    log.info(f"[ws] Kullanıcı {user_id} bağlandı")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        log.info(f"[ws] Kullanıcı {user_id} ayrıldı")
        active_connections.pop(user_id, None)

@app.on_event("startup")
async def on_startup():
    import asyncio
    asyncio.create_task(start_redis_listener())
