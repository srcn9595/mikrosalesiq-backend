from pymongo import MongoClient
from datetime import datetime
from typing import Optional, Union
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

chat_sessions_coll = db["chat_sessions"]
chat_messages_coll = db["chat_messages"]

def create_chat_session(user_id: str) -> str:
    session_id = f"session_{datetime.utcnow().timestamp()}"
    chat_sessions_coll.insert_one({
        "session_id": session_id,
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "title": None
    })
    return session_id

def create_chat_session_if_needed(user_id: str, session_id: Optional[str]) -> str:
    if session_id:
        exists = chat_sessions_coll.find_one({"session_id": session_id})
        if exists:
            return session_id  # ✅ mevcut oturum varsa devam
    return create_chat_session(user_id)

def insert_message(
    session_id: str,
    role: str,
    content: Union[str, dict],
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    email: Optional[str] = None
):
    doc = {
        "session_id": session_id,
        "role": role,
        "timestamp": datetime.utcnow()
    }

    if isinstance(content, dict):
        doc["type"] = content.get("type", "json")
        doc["content"] = content.get("content")
    else:
        doc["type"] = "text"
        doc["content"] = content

    if user_id:
        doc["user_id"] = user_id
    if username:
        doc["username"] = username
    if email:
        doc["email"] = email

    chat_messages_coll.insert_one(doc)


