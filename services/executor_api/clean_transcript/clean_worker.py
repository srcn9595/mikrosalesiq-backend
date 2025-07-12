#!/usr/bin/env python3

import os, time, json, logging, redis, pymongo
from datetime import datetime
from pathlib import Path
from clean_transcript.clean_utils import generate_cleaned_transcript_sync, chunks_by_tokens
from queue_utils import mark_semantic_enqueued
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

def is_summary_valid(call_data):
    af = call_data.get("audio_features")
    if not af or not isinstance(af, dict):
        return False

    # Aşağıdaki metriklerin 0 olması, işlem yapılmadığını gösterebilir
    # Bu yüzden en azından biri 0'dan büyük olmalı
    metrics = [
        af.get("agent_pitch_variance", 0),
        af.get("customer_pitch_variance", 0),
        af.get("speaking_rate_customer", 0),
        af.get("speaking_rate_agent", 0),
        af.get("agent_talk_ratio", 0),
        af.get("customer_filler_count", 0)
    ]

    return any(m > 0 for m in metrics)


def try_enqueue_mini_rag_if_all_cleaned(customer_num: str, notification_id: str):
    doc = audio.find_one({"customer_num": customer_num}, {"calls": 1, "mini_rag": 1})
    calls = doc.get("calls", [])

    if not calls or len(calls) == 0:
        return

    for c in calls:
        if c.get("status") != "cleaned":
            log.warning(f"[BLOCKED] {customer_num} → {c.get('call_id')} henüz 'cleaned' değil.")
            return
        if not is_summary_valid(c):
            log.warning(f"[BLOCKED] {customer_num} → {c.get('call_id')} için summary geçersiz.")
            return

    if doc.get("mini_rag", {}).get("generated_at"):
        log.info(f"[SKIP] {customer_num} için mini_rag zaten mevcut, tekrar kuyruğa alınmadı.")
        return

    from queue_utils import enqueue_mini_rag
    if notification_id:
        enqueue_mini_rag(customer_num, notification_id=notification_id, mongo=db)
        log.info(f"[✅ TRIGGERED] {customer_num} → Tüm çağrılar cleaned ve valid → mini_rag kuyruğa eklendi.")
    else:
        log.warning(f"[BLOCKED] {customer_num}: notification_id yok, mini_rag atlanıyor.")


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
            if len(chunks) > 1:
                raise ValueError(f"{call_id} için transcript çok uzun, tek parçada işlenmeli.")

            llm_response = generate_cleaned_transcript_sync(call_id, raw_text, call_date, audio_features=call.get("audio_features", {}))


            if not llm_response.strip():
                raise ValueError(f"LLM yanıtı boş geldi! call_id={call_id}")

            try:
                parsed = json.loads(llm_response)
            except json.JSONDecodeError as e:
                raise ValueError(f"Yanıt JSON değil: {e}\nYanıt:\n{llm_response[:500]}")

            # Dosyaya sadece transcript yaz
            Path(CLEANED_DIR, customer_num).mkdir(parents=True, exist_ok=True)
            Path(CLEANED_DIR, customer_num, f"{call_id}.txt").write_text(parsed["cleaned_transcript"], encoding="utf-8")

            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.cleaned_transcript": parsed.get("cleaned_transcript", ""),
                    "calls.$.difficulty_level": parsed.get("difficulty_level", ""),
                    "calls.$.sentiment": parsed.get("sentiment", ""),
                    "calls.$.direction": parsed.get("direction", ""),
                    "calls.$.audio_analysis_commentary": parsed.get("audio_analysis_commentary", []),
                    "calls.$.needs": parsed.get("needs", []),
                    "calls.$.status": "cleaned",
                    "calls.$.cleaned_at": datetime.utcnow()
                }}
            )
            log.info(f"✅ Temizleme tamam: {call_id}")

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

                # Semantic embedding kuyruğuna al
                if call.get("embedding_created_at"):
                    log.info(f"{call_id} → Zaten embedding yapılmış, kuyruğa eklenmedi.")
                else:
                    mark_semantic_enqueued(call_id)
                    log.info(f"{call_id} → Semantic kuyruğa eklendi.")

                # Audio summary valid mi kontrol et
                audio_doc = audio.find_one({"calls.call_id": call_id}, {"calls.$": 1})
                call_data = audio_doc["calls"][0]
                if is_summary_valid(call_data):
                    finalize_notification_if_ready(db, notif_id)
                    try_enqueue_mini_rag_if_all_cleaned(customer_num, notification_id=notif_id)
                    log.info(f"🔁 Notification finalize edildi & mini_rag kontrolü yapıldı: {call_id}")
                else:
                    log.warning(f"🕓 audio_features_summary eksik → finalize/mini_rag tetiklenmedi: {call_id}")    


        except Exception as e:
            log.error(f"❌ Temizleme hatası: {call_id} - {e}")
            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "error", "calls.$.error": str(e)}}
            )
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
                log.info(f"Notification {notif_id} güncellendi: {call_id} için temizleme hatası.")
        update_job_status(customer_num)

if __name__ == "__main__":
    main()
