import redis
import os
import json
from bson import json_util
import logging

log = logging.getLogger("ws_notify")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
rds_pub = redis.from_url(REDIS_URL, decode_responses=True)

def notify_user_ws(user_id: str, notification_id: str, event_type: str = "notification_done", extra: dict = None):
    message = {
        "type": event_type,
        "notification_id": notification_id,
    }
    if extra:
        message.update(extra)
    
    channel = f"user:{user_id}"
    encoded = json_util.dumps(message)
    rds_pub.publish(channel, encoded)
    log.info(f"[ws_notify] → user:{user_id} kanalına gönderildi: {encoded}")
