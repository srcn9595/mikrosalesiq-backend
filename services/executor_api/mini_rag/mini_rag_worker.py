#!/usr/bin/env python3
# services/executor_api/mini_rag/mini_rag_worker.py
# -------------------------------------------------
# • Tüm görüşmeler CLEANED değilse mini-RAG üretmez
# • Eksik/hatalı görüşmeleri transcribe kuyruğuna atar
# • Özet başarıyla yazılınca _MINI_RAG_ENQUEUED_SET’ten siler


import os, time, logging, pymongo, redis
from dotenv import load_dotenv
from langfuse import Langfuse
from typing import List, Dict, Any
import json
from queue_utils import (
    _MINI_RAG_ENQUEUED_SET,
    rds,  # global Redis bağlantısı
)
from mini_rag.mini_rag_utils import (
    merge_transcripts, build_mini_rag_payload, generate_openai_summary, aggregate_audio_features
)
from mongo_utils import save_mini_rag_summary

from shared_lib.notification_utils import (
    update_job_in_notification,
    finalize_notification_if_ready
)
from queue_utils import is_customer_embedding_enqueued, mark_customer_embedding_enqueued
load_dotenv()

# ─────────────── ENV ───────────────
MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB    = os.getenv("MONGO_DB", "mikrosalesiq")
REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME  = os.getenv("MINI_RAG_QUEUE", "mini_rag_jobs")
MODEL       = os.getenv("MINI_RAG_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("MINI_RAG_TEMP", "0.3"))

# ─────────────── Clients ───────────────
mongo_client = pymongo.MongoClient(MONGO_URI)
db           = mongo_client[MONGO_DB]
audio_jobs   = db["audio_jobs"]
rds          = redis.from_url(REDIS_URL)

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

# ─────────────── Logging ───────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mini_rag_worker")

# ─────────────── Helpers ───────────────
def try_enqueue_customer_embedding(customer_num: str):
    doc = audio_jobs.find_one({"customer_num": customer_num}, {
        "customer_profiles_rag.embedding_created_at": 1
    })

    if doc and doc.get("customer_profiles_rag", {}).get("embedding_created_at"):
        log.info(f"[SKIP] {customer_num} zaten vektör embedding yapılmış.")
        return

    if is_customer_embedding_enqueued(customer_num):
        log.info(f"[SKIP] {customer_num} zaten kuyruğa alınmış.")
        return

    mark_customer_embedding_enqueued(customer_num)
    log.info(f"[✅ ENQUEUED] {customer_num} → customer_embedding_jobs kuyruğuna alındı.")


def get_cleaned_transcripts_ordered(customer_num: str) -> List[Dict[str, Any]]:
    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        return []
    calls = [c for c in doc.get("calls", []) if c.get("cleaned_transcript")]
    calls.sort(key=lambda c: c.get("call_date") or "")
    return [
        {
            "call_id":     c["call_id"],
            "call_date":   c.get("call_date"),
            "agent_email": c.get("agent_email"),
            "transcript":  c["cleaned_transcript"],
        }
        for c in calls
    ]

def get_unprocessed_calls(customer_num: str) -> List[str]:
    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        return []
    return [c["call_id"] for c in doc.get("calls", []) if not c.get("cleaned_transcript")]

def enqueue_transcription(call_id: str) -> None:
    rds.lpush("transcribe_jobs", call_id)
    log.info("Enqueued transcription for call: %s", call_id)

def dequeue_clean_for_customer(customer_num: str):
    """
    Belirtilen customer_num'a ait tüm çağrıların clean_enqueued_set'ten silinmesini sağlar.
    """
    doc = audio_jobs.find_one({"customer_num": customer_num})
    if not doc:
        return
    for call in doc.get("calls", []):
        cid = call.get("call_id")
        if cid:
            rds.srem("clean_enqueued_set", cid)


# ─────────────── Main Loop ───────────────
def run() -> None:
    log.info("Mini-RAG worker started.")
    while True:
        item = rds.rpop(QUEUE_NAME)
        if not item:
            time.sleep(3)
            continue

        # ---- Kuyruk item’ını parse et ------------------------------------
        try:
            ctx            = json.loads(item.decode())
            customer_num   = ctx["customer_num"]
            notification_id = ctx.get("notification_id")
        except Exception:
            customer_num    = item.decode()
            notification_id = None
        # ------------------------------------------------------------------

        log.info("Processing %s …", customer_num)

        # Özet zaten varsa → geç
        if audio_jobs.find_one(
            {"customer_num": customer_num, "mini_rag.summary": {"$exists": True}}
        ):
            rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)
            dequeue_clean_for_customer(customer_num)
            log.info("⏩  Skipped – summary already exists.")
            continue

        # Tüm cleaned’leri kontrol et
        cleaned  = get_cleaned_transcripts_ordered(customer_num)
        pending  = get_unprocessed_calls(customer_num)
        if pending:
            for cid in pending:
                enqueue_transcription(cid)
            log.info("Deferred – %d call(s) still pending.", len(pending))
            continue

        # ---- Mini-RAG oluştur -------------------------------------------
        doc          = audio_jobs.find_one({"customer_num": customer_num})
        merged       = merge_transcripts(cleaned)
        audio_feats  = aggregate_audio_features(doc.get("calls", []))
        payload      = build_mini_rag_payload(cleaned, audio_features=audio_feats)
        messages     = payload["messages"]
        confidence   = payload["confidence"]
        token_count  = payload["token_count"]

        with langfuse.start_as_current_span(
            name="mini_rag_worker",
            input={"customer_num": customer_num, "messages": messages},
            metadata={"component": "mini_rag_worker"},
        ) as span:
            try:
                parsed = generate_openai_summary(messages, model=MODEL,
                                                 temperature=TEMPERATURE)
                span.update(output={"parsed": parsed})

            # ---------- HATA: özet üretilemedi ----------------------------
            except Exception as e:
                log.error("OpenAI error: %s", e)
                span.update(output={"error": str(e)})

                # Bildirimi ERROR yap
                if notification_id:
                    update_job_in_notification(
                        mongo=db,
                        notification_id=notification_id,
                        customer_num=customer_num,
                        job_status="error",
                        error=str(e),
                    )
                finalize_notification_if_ready(db, notification_id)
                # Kuyruk ve SET temizle (yeniden deneme yok)
                rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)
                dequeue_clean_for_customer(customer_num)
                continue
        # ---------- /try-except ------------------------------------------

        # Mongo’ya kaydet
        save_mini_rag_summary(
            customer_num      = customer_num,
            summary_json      = parsed,
            merged_transcript = merged,
            confidence        = confidence,
            token_count       = token_count,
            audio_features    = audio_feats
        )
        # ✅ Customer embedding kuyruğuna al
        try_enqueue_customer_embedding(customer_num)

        # Kuyruk & SET’ten çıkar
        rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)
        log.info("✅ Mini-RAG done: %s (calls=%d, tokens=%d)",
                 customer_num, len(cleaned), token_count)
        log.info("Notification ID: %s", notification_id)
        # Bildirimi DONE yap
        if notification_id:
            from shared_lib.notification_utils import update_job_in_notification
            update_job_in_notification(
                mongo=db,
                notification_id=notification_id,
                customer_num=customer_num,
                job_status="done",
                result={"summary_ready": True, "customer_num": customer_num},
            )
            finalize_notification_if_ready(db, notification_id)
            log.info("Notification %s → done.", notification_id)


if __name__ == "__main__":
    run()

