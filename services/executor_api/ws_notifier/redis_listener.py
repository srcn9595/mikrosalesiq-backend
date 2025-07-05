import asyncio
import redis.asyncio as redis
import os
import json
import logging
from fastapi import WebSocket

log = logging.getLogger("redis_listener")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
rds = redis.from_url(REDIS_URL, decode_responses=True)

# Bu aktif bağlantılar main.py'den inject edilecek
active_connections: dict[str, WebSocket] = {}

async def start_redis_listener():
    pubsub = rds.pubsub()
    await pubsub.psubscribe("user:*")

    log.info("[listener] Redis kanalına bağlandı")

    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue

        channel = message["channel"]
        data = message["data"]
        user_id = channel.split(":")[1]
        ws = active_connections.get(user_id)

        if ws:
            try:
                await ws.send_text(data)
                log.info(f"[listener] → {user_id}: {data}")
            except:
                log.warning(f"[listener] → {user_id} mesajı gönderilemedi")
