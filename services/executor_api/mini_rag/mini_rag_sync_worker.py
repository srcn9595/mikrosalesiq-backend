# services/executor_api/mini_rag_sync_worker.py

import os
import json
import logging
import pymongo
from dotenv import load_dotenv

from mini_rag.mini_rag_utils import (
    build_mini_rag_payload,
    merge_transcripts,
    generate_openai_summary
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


def generate_mini_rag_output(customer_num: str) -> dict:
    log.info(f"⏱ Mini-RAG senkron başlatıldı: {customer_num}")

    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        raise ValueError(f"{customer_num} için kayıt bulunamadı.")

    cleaned_transcripts = [
        {
            "call_id": c.get("call_id"),
            "call_date": c.get("call_date"),
            "transcript": c.get("cleaned_transcript")
        }
        for c in doc.get("calls", [])
        if c.get("cleaned_transcript") and c["cleaned_transcript"].strip()
    ]

    if not cleaned_transcripts:
        raise ValueError(f"{customer_num} için temizlenmiş transcript bulunamadı.")

    merged_transcript = merge_transcripts(cleaned_transcripts)
    payload = build_mini_rag_payload(cleaned_transcripts)
    messages = payload["messages"]
    confidence = payload["confidence"]
    token_count = payload["token_count"]

    parsed = generate_openai_summary(messages, model=MODEL, temperature=TEMPERATURE)

    # Mongo’ya yaz
    save_mini_rag_summary(
        customer_num=customer_num,
        summary_json=parsed,
        merged_transcript=merged_transcript,
        confidence=confidence,
        token_count=token_count
    )

    log.info(f"✅ Mini-RAG senkron tamamlandı: {customer_num}")
    return parsed
