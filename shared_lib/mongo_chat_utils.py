# shared_lib/mongo_chat_utils.py

from pymongo import MongoClient
from datetime import datetime
from typing import Optional, Union, List, Dict
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

chat_sessions_coll = db["chat_sessions"]
chat_messages_coll = db["chat_messages"]

def create_chat_session(user_id: str, username: Optional[str] = None, email: Optional[str] = None) -> str:
    session_id = f"session_{datetime.utcnow().timestamp()}"
    chat_sessions_coll.insert_one({
        "session_id": session_id,
        "user_id": user_id,
        "username": username,
        "email": email,
        "created_at": datetime.utcnow(),
        "title": None
    })
    return session_id

def create_chat_session_if_needed(user_id: str, session_id: Optional[str], username: Optional[str] = None, email: Optional[str] = None) -> str:
    if session_id:
        exists = chat_sessions_coll.find_one({"session_id": session_id})
        if exists:
            return session_id
    return create_chat_session(user_id, username=username, email=email)

def get_chat_messages_for_session(session_id: str, user_id: Optional[str] = None) -> List[Dict]:
    query = {"session_id": session_id}
    if user_id:
        query["user_id"] = user_id

    messages = chat_messages_coll.find(query).sort("timestamp", 1)  # eski → yeni sıralı
    return [
        {
            "role": msg.get("role", "bot"),
            "type": msg.get("type", "text"),
            "content": msg.get("content")
        }
        for msg in messages
    ]

def insert_message(session_id: str, role: str, content: Union[str, dict], user_id: Optional[str] = None, username: Optional[str] = None, email: Optional[str] = None,fcm_token: Optional[str] = None):
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

    if user_id: doc["user_id"] = user_id
    if username: doc["username"] = username
    if email: doc["email"] = email
    if fcm_token: doc["fcm_token"]=fcm_token

    res = chat_messages_coll.insert_one(doc)
    return str(res.inserted_id) 


def get_chat_sessions(user_id: str) -> List[Dict]:
    sessions = chat_sessions_coll.find(
        {"user_id": user_id},
        {"_id": 0, "session_id": 1, "title": 1, "created_at": 1}
    ).sort("created_at", -1)
    return list(sessions)
