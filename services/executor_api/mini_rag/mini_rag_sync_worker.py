# services/executor_api/mini_rag_sync_worker.py

import os
import json
import logging
import pymongo
from dotenv import load_dotenv
from langfuse import Langfuse
from queue_utils import _MINI_RAG_ENQUEUED_SET, rds 
from shared_lib.notification_utils import update_notification_status
from mini_rag.mini_rag_utils import (
    build_mini_rag_payload,
    merge_transcripts,
    generate_openai_summary,
    aggregate_audio_features
)
from mongo_utils import save_mini_rag_summary

# ──────────────── ENV & LOGGING ────────────────
load_dotenv()

log = logging.getLogger("mini_rag_sync_worker")
logging.basicConfig(level=logging.INFO)

# ──────────────── CLIENTS ────────────────
mongo_client = pymongo.MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client[os.getenv("MONGO_DB", "mikrosalesiq")]
audio_jobs = db["audio_jobs"]

MODEL = os.getenv("MINI_RAG_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("MINI_RAG_TEMP", "0.3"))

# ──────────────── Langfuse ────────────────
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)


def generate_mini_rag_output(customer_num: str, notification_id: str = None) -> dict:
    log.info(f"⏱ Mini-RAG senkron başlatıldı: {customer_num}")

    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        raise ValueError(f"{customer_num} için kayıt bulunamadı.")

    cleaned_transcripts = [
        {
            "call_id": c.get("call_id"),
            "call_date": c.get("call_date"),
            "agent_email":  c.get("agent_email"),
            "transcript": c.get("cleaned_transcript")
        }
        for c in doc.get("calls", [])
        if c.get("cleaned_transcript") and c["cleaned_transcript"].strip()
    ]

    if not cleaned_transcripts:
        raise ValueError(f"{customer_num} için temizlenmiş transcript bulunamadı.")

    merged_transcript = merge_transcripts(cleaned_transcripts)
    audio_features = aggregate_audio_features(doc.get("calls", []))
    log.info(f"{audio_features}")
    payload     = build_mini_rag_payload(cleaned_transcripts, audio_features=audio_features)
    messages = payload["messages"]
    confidence = payload["confidence"]
    token_count = payload["token_count"]

    with langfuse.start_as_current_span(
        name="mini_rag_sync_worker",
        input={"customer_num": customer_num, "messages": messages},
        metadata={"component": "mini_rag_sync_worker"},
    ) as span:
        try:
            parsed = generate_openai_summary(messages, model=MODEL, temperature=TEMPERATURE)
            span.update(output={"parsed": parsed})
        except Exception as e:
            log.error("OpenAI / parse error: %s", e)
            span.update(output={"error": str(e)})
            raise e

    # Mongo’ya yaz
    save_mini_rag_summary(
        customer_num=customer_num,
        summary_json=parsed,
        merged_transcript=merged_transcript,
        confidence=confidence,
        token_count=token_count,
        audio_features=audio_features
    )
    rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)
    log.info("SET’ten silindi: %s", customer_num)
    log.info(f"✅ Mini-RAG senkron tamamlandı: {customer_num}")

    # --- Notification güncelle ---
    log.info(f"MINI_RAG_SYNC_WORKER Notification ID: {notification_id}")
    if notification_id:
        try:
            update_notification_status(
                mongo=db,  # mongo client (ör: pymongo database instance)
                notification_id=notification_id,
                status="done",
                result=parsed
            )
            log.info(f"🔔 Notification {notification_id} 'done' olarak güncellendi.")
        except Exception as e:
            log.error(f"Notification güncelleme hatası: {e}")

    return parsed
