from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from shared_lib.mongo_chat_utils import (
    get_chat_sessions,
    insert_message,
    create_chat_session_if_needed
)
from shared_lib.jwt_utils import verify_token
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Next.js için
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/chat_sessions")
async def list_chat_sessions(request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Yetkisiz")

    user_info = verify_token(auth)
    user_id = user_info.get("sub")

    sessions = get_chat_sessions(user_id)

    return {
        "type": "json",
        "content": {"items": sessions}
    }

@app.get("/api/chat_messages/{session_id}")
async def get_messages_for_session(session_id: str, request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Yetkisiz")

    user_info = verify_token(auth)
    user_id = user_info.get("sub")

    from shared_lib.mongo_chat_utils import get_chat_messages_for_session

    messages = get_chat_messages_for_session(session_id=session_id, user_id=user_id)

    return {
        "type": "json",
        "content": {
            "items": messages
        }
    }
