import os
import httpx
from fastapi import HTTPException

FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY")

async def send_fcm_notification(token: str, notification_id: str, title: str, message: str = ""):
    if not FCM_SERVER_KEY:
        raise HTTPException(status_code=500, detail="FCM server key not set.")

    headers = {
        "Authorization": f"key={FCM_SERVER_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "to": token,
        "notification": {
            "title": title,
            "body": message
        },
        "data": {
            "notification_id": notification_id
        }
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post("https://fcm.googleapis.com/fcm/send", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
