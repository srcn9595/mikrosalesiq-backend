import os
import json
import pymongo
import redis
import logging
from datetime import datetime
from clean_transcript.clean_utils import generate_cleaned_transcript_sync, chunks_by_tokens
from queue_utils import is_semantic_enqueued, mark_semantic_enqueued

# ─────────────── LOGGING
log = logging.getLogger("clean_sync_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")


MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB   = os.getenv("MONGO_DB", "mikrosalesiq")
REDIS_URL  = os.getenv("REDIS_URL", "redis://localhost:6379")
AUDIO_COLL = "audio_jobs"

client = pymongo.MongoClient(MONGO_URI)
db     = client[MONGO_DB]
audio  = db[AUDIO_COLL]
rds    = redis.from_url(REDIS_URL)

def clean_transcript_sync(call_id: str) -> str:
    doc = audio.find_one(
        {"calls.call_id": call_id},
        {"calls.$": 1, "customer_num": 1}
    )
    if not doc or not doc.get("calls"):
        raise ValueError(f"{call_id} için veri bulunamadı.")

    call = doc["calls"][0]
    transcript = call.get("transcript", "")
    if not transcript:
        raise ValueError(f"{call_id} için transcript boş.")
    
    call_date = call.get("call_date", "Tarih bilinmiyor")
    chunks = chunks_by_tokens(transcript, 8000)

    if len(chunks) > 1:
        raise ValueError(f"{call_id} için transcript çok uzun, tek parçada işlenmeli.")

    # 🎯 LLM'den JSON bekleniyor
    llm_response = generate_cleaned_transcript_sync(call_id, transcript, call_date)

    try:
        parsed = json.loads(llm_response)
    except Exception as e:
        raise ValueError(f"Yanıt JSON formatında değil: {e}\n\nYanıt: {llm_response[:300]}")

    # 🎯 Mongo güncellemesi: tüm alanlar birlikte yazılır
    update_fields = {
        "calls.$.cleaned_transcript": parsed.get("cleaned_transcript", ""),
        "calls.$.difficulty_level": parsed.get("difficulty_level", ""),
        "calls.$.sentiment": parsed.get("sentiment", ""),
        "calls.$.direction": parsed.get("direction", ""),
        "calls.$.audio_analysis_commentary": parsed.get("audio_analysis_commentary", []),
        "calls.$.needs": parsed.get("needs", []),
        "calls.$.status": "cleaned",
        "calls.$.cleaned_at": datetime.utcnow()
    }

    audio.update_one(
        {"calls.call_id": call_id},
        {"$set": update_fields}
    )
    
    #Semantic embedding kuyruğa ekle
    call_data = doc["calls"][0]
    if call_data.get("embedding_created_at"):
        log.info(f"{call_id} → Zaten embedding yapılmış, kuyruğa eklenmedi.")
    else:
        mark_semantic_enqueued(call_id)

    return parsed["cleaned_transcript"]
