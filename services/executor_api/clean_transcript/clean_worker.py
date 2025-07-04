#!/usr/bin/env python3

import os, time, logging, redis, pymongo
from datetime import datetime
from pathlib import Path
from clean_transcript.clean_utils import generate_cleaned_transcript_sync, chunks_by_tokens
from shared_lib.notification_utils import (
    get_notification_id_for_call, 
    update_job_in_notification,
    finalize_notification_if_ready
)
from typing import List

# ─────────────── ENV
MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB     = os.getenv("MONGO_DB", "mikrosalesiq")
REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379")
CLEANED_DIR  = os.getenv("CLEANED_OUTPUT_ROOT", "cleaned_output")
CLEAN_QUEUE  = "clean_jobs"
AUDIO_COLL   = "audio_jobs"

# ─────────────── CLIENTS
db     = pymongo.MongoClient(MONGO_URI)[MONGO_DB]
rds    = redis.from_url(REDIS_URL)
audio = db[AUDIO_COLL]

# ─────────────── LOGGING
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
log = logging.getLogger("clean_worker")

def try_enqueue_mini_rag_if_all_cleaned(customer_num: str, notification_id: str):
    """
    Tüm çağrılar 'cleaned' ise mini_rag kuyruğuna alır. 
    Sadece notification_id varsa çalışır (manuel tetiklenmeyenler için asla trigger yapma!)
    """
    doc = audio.find_one({"customer_num": customer_num}, {"calls.status": 1})
    calls = doc.get("calls", [])
    if all(c.get("status") == "cleaned" for c in calls) and len(calls) > 0:
        from queue_utils import enqueue_mini_rag
        # SADECE notification_id varsa triggerla!
        if notification_id:
            enqueue_mini_rag(customer_num, notification_id=notification_id, mongo=db)
            log.info(f"[AUTO-TRIGGER] {customer_num} için tüm çağrılar cleaned → mini_rag kuyruğuna eklendi.")
        else:
            # Otomatik tetikleme yapılmaz!
            log.warning(f"[AUTO-TRIGGER BLOCKED] {customer_num}: notification_id yok, mini_rag atlanıyor.")



def update_job_status(customer_num: str):
    doc = audio.find_one({"customer_num": customer_num}, {"calls.status": 1})
    if not doc:
        return
    statuses = [c.get("status") for c in doc.get("calls", [])]
    if all(s == "cleaned" for s in statuses):
        new_status = "completed"
    elif "error" in statuses:
        new_status = "error"
    elif any(s in ["transcribed", "downloaded"] for s in statuses):
        new_status = "in_progress"
    else:
        new_status = "queued"
    audio.update_one({"customer_num": customer_num}, {"$set": {"job_status": new_status}})

def main(poll_interval: int = 5):
    log.info("🧹 clean_worker başlatıldı – Kuyruk: %s", CLEAN_QUEUE)
    while True:
        job = rds.lpop(CLEAN_QUEUE)
        if not job:
            time.sleep(poll_interval)
            continue
        call_id = job.decode()
        doc = audio.find_one({"calls.call_id": call_id}, {"calls.$": 1, "customer_num": 1})
        if not doc or not doc.get("calls"):
            log.warning(f"call_id={call_id} için kayıt bulunamadı.")
            continue
        call = doc["calls"][0]

        if call.get("status") == "cleaned" and call.get("cleaned_transcript"):
           log.info(f"call_id={call_id} zaten cleaned, iş atlandı.")
           continue
        raw_text = call.get("transcript")
        if not raw_text:
            log.warning(f"call_id={call_id} transcript boş.")
            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "error", "calls.$.error": "no transcript"}}
            )
            continue
        customer_num = doc["customer_num"]
        call_date    = call.get("call_date", "Tarih bilinmiyor")
        try:
            chunks = chunks_by_tokens(raw_text, 8000)
            cleaned = "\n\n".join(
                generate_cleaned_transcript_sync(call_id, part, call_date)
                for part in chunks
            )

            # Write to disk
            Path(CLEANED_DIR, customer_num).mkdir(parents=True, exist_ok=True)
            Path(CLEANED_DIR, customer_num, f"{call_id}.txt").write_text(cleaned, encoding="utf-8")

            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "cleaned",
                    "calls.$.cleaned_transcript": cleaned,
                    "calls.$.cleaned_at": datetime.utcnow()
                }}
            )
            log.info(f"✅ Temizleme tamam: {call_id}")
            # --- Notification güncelle (success) ---
            notif_id = get_notification_id_for_call(db, call_id)
            if notif_id:
                update_job_in_notification(
                    mongo=db,
                    notification_id=notif_id,
                    customer_num=customer_num,
                    call_id=call_id,
                    job_status="done",
                    result={"cleaned": True}
                )
                finalize_notification_if_ready(db, notif_id)
                log.info(f"Notification {notif_id} güncellendi: {call_id} için temizleme tamamlandı.")

            try_enqueue_mini_rag_if_all_cleaned(customer_num, notification_id=notif_id)
        except Exception as e:
            log.error(f"❌ Temizleme hatası: {call_id} - {e}")
            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "error", "calls.$.error": str(e)}}
            )
            # --- Notification güncelle (error) ---
            notif_id = get_notification_id_for_call(db, call_id)
            if notif_id:
                update_job_in_notification(
                    mongo=db,
                    notification_id=notif_id,
                    customer_num=customer_num,
                    call_id=call_id,
                    job_status="error",
                    error=str(e)
                )
                finalize_notification_if_ready(db, notif_id)
                log.info(f"Notification {notif_id} güncellendi: {call_id} için temizleme hatası.")
        update_job_status(customer_num)

if __name__ == "__main__":
    main()
