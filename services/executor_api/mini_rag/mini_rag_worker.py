# services/executor_api/mini_rag_worker.py

import os
import time
import logging
import pymongo
import redis
from dotenv import load_dotenv
from queue_utils import _MINI_RAG_ENQUEUED_SET, rds 
from mini_rag.mini_rag_utils import (
    build_mini_rag_payload,
    merge_transcripts,
    generate_openai_summary
)

from mongo_utils import save_mini_rag_summary
from langfuse import Langfuse

# ──────────────── ENV & CONFIG ────────────────
load_dotenv()

MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB    = os.getenv("MONGO_DB", "mikrosalesiq")
REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME  = os.getenv("MINI_RAG_QUEUE", "mini_rag_jobs")
MODEL       = os.getenv("MINI_RAG_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("MINI_RAG_TEMP", "0.3"))

# ──────────────── Clients ────────────────
mongo_client = pymongo.MongoClient(MONGO_URI)
db           = mongo_client[MONGO_DB]
audio_jobs   = db["audio_jobs"]
rds          = redis.from_url(REDIS_URL)

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

# ──────────────── Logging ────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("mini_rag_worker")


# ──────────────── Helpers ────────────────
def get_cleaned_transcripts_ordered(customer_num: str):
    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        return []

    calls = [
        c for c in doc.get("calls", [])
        if c.get("cleaned_transcript") and c["cleaned_transcript"].strip()
    ]

    sorted_calls = sorted(calls, key=lambda c: c.get("call_date") or "")

    return [
        {
            "call_id":    c.get("call_id"),
            "call_date":  c.get("call_date"),
            "agent_email":  c.get("agent_email"),
            "transcript": c.get("cleaned_transcript")
        }
        for c in sorted_calls
    ]


def get_unprocessed_calls(customer_num: str):
    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        return []
    return [
        c["call_id"]
        for c in doc.get("calls", [])
        if not c.get("cleaned_transcript")
    ]


def enqueue_transcription(call_id: str):
    rds.lpush("transcribe_jobs", call_id)
    log.info(f"Enqueued transcription for call: {call_id}")


# ──────────────── Main Loop ────────────────
def run():
    log.info("Mini-RAG worker started.")
    while True:
        item = rds.rpop(QUEUE_NAME)
        if not item:
            time.sleep(3)
            continue

        customer_num = item.decode()
        log.info(f"Processing customer: {customer_num}")

        doc = audio_jobs.find_one({"customer_num": customer_num}, {"mini_rag.summary": 1})
        if doc and doc.get("mini_rag", {}).get("summary"):
            log.info(f"Mini-RAG already exists for {customer_num}, skipping...")
            continue

        cleaned_transcripts = get_cleaned_transcripts_ordered(customer_num)
        if not cleaned_transcripts:
            pending = get_unprocessed_calls(customer_num)
            if pending:
                enqueue_transcription(pending[0])
                log.info(f"Transcript eksik; transcription kuyruğa alındı: {customer_num}")
            else:
                log.warning(f"Hiç görüşme yok: {customer_num}")
            continue

        merged_transcript = merge_transcripts(cleaned_transcripts)
        payload = build_mini_rag_payload(cleaned_transcripts)
        messages = payload["messages"]
        confidence = payload["confidence"]
        token_count = payload["token_count"]

        with langfuse.start_as_current_span(
            name="mini_rag_worker",
            input={"customer_num": customer_num, "messages": messages},
            metadata={"component": "mini_rag_worker"}
        ) as span:
            try:
                parsed = generate_openai_summary(messages, model=MODEL, temperature=TEMPERATURE)
                span.update(output={"parsed": parsed})
            except Exception as e:
                log.error(f"❌ OpenAI veya parse hatası: {e}")
                span.update(output={"error": str(e)})
                continue

        save_mini_rag_summary(
            customer_num=customer_num,
            summary_json=parsed,
            merged_transcript=merged_transcript,
            confidence=confidence,
            token_count=token_count
        )
        rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)
        log.info("SET’ten silindi: %s", customer_num)
        log.info(f"✅ Mini-RAG tamamlandı: {customer_num} (tokens={token_count})")


if __name__ == "__main__":
    run()
