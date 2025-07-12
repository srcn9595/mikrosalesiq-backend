# semantic_async_worker.py

import os
import time
import logging
from typing import Optional
from datetime import datetime
from bson.objectid import ObjectId

import redis
import pymongo
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Distance, VectorParams
from semantic_search.snapshot_manager import save_snapshot_if_needed, get_total_semantic_count
from uuid import uuid5, NAMESPACE_DNS

from semantic_search.embedding_utils import get_call_embedding, get_embedding_metadata
from queue_utils import dequeue_semantic 


# ✔ Ortam değişkenleri
REDIS_URL           = os.getenv("REDIS_URL", "redis://localhost:6379")
MONGO_URI           = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB            = os.getenv("MONGO_DB", "mikrosalesiq")
COLL_AUDIO          = "audio_jobs"
COLL_SEMANTIC       = "semantic_calls"
QDRANT_HOST         = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT         = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION   = "semantic_calls"

# ✔ Bağlantılar
rds     = redis.from_url(REDIS_URL)
mongo   = pymongo.MongoClient(MONGO_URI)[MONGO_DB]
qdrant  = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# ✔ Logger
log = logging.getLogger("semantic_async_worker")
logging.basicConfig(level=logging.INFO)

# ✔ Redis kuyruk isimleri
SEMANTIC_QUEUE_KEY     = "semantic_jobs"
SEMANTIC_ENQUEUED_SET  = "semantic_enqueued_set"


# ✔ Yardımcı fonksiyon: transcript + metadata
def get_semantic_input(call_id: str) -> Optional[dict]:
    try:
        doc = mongo[COLL_AUDIO].find_one(
            {"calls.call_id": call_id},
            {"customer_num": 1, "calls": 1}
        )

        if not doc or "calls" not in doc:
            log.warning(f"❌ Çağrı bulunamadı: {call_id}")
            return None

        call = next((c for c in doc["calls"] if c.get("call_id") == call_id), None)
        if not call:
            log.warning(f"❌ Çağrı array içinde bulunamadı: {call_id}")
            return None

        transcript = call.get("cleaned_transcript")
        if not transcript:
            log.warning(f"⚠️ Transcript boş: {call_id}")
            return None

        return {
            "call_id": call_id,
            "customer_num": doc["customer_num"],
            "transcript": transcript,
            "call_date": call.get("call_date"),
            "direction": call.get("direction"),
            "agent_email": call.get("agent_email"),
            "sentiment": call.get("sentiment"),
            "sector": call.get("sector"),
            "difficulty_level": call.get("difficulty_level"),
            "customer_type": call.get("customer_type"),
            "audio_analysis_commentary": call.get("audio_analysis_commentary", []),
            "needs": call.get("needs", []),
            "audio_features": call.get("audio_features", {})
        }

    except Exception as e:
        log.exception(f"🚨 get_semantic_input hatası ({call_id}): {e}")
        return None


# ✔ Ana işleme fonksiyonu
def process_call_id(call_id: str):
    data = get_semantic_input(call_id)
    if not data:
        log.warning(f"⚠️ Veri eksik/bulunamadı: {call_id}")
        return

    embedding = get_call_embedding(data["transcript"])
    if not embedding:
        log.error(f"❌ Embedding alınamadı: {call_id}")
        return

    try:
        collections = [c.name for c in qdrant.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            log.info(f"ℹ️ Koleksiyon yok, oluşturuluyor: {QDRANT_COLLECTION}")
            qdrant.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=1536,
                    distance=Distance.COSINE
                )
            )
            log.info(f"📦 Koleksiyon oluşturuldu: {QDRANT_COLLECTION}")
        else:
            log.info(f"✅ Koleksiyon zaten mevcut: {QDRANT_COLLECTION}")
    except Exception as e:
        log.exception(f"🚨 Qdrant koleksiyon kontrol/oluşturma hatası: {e}")
        return

    point_id = str(uuid5(NAMESPACE_DNS, call_id))
    embedding_metadata = get_embedding_metadata()

    try:
        qdrant.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "call_id": call_id,
                        "customer_num": data["customer_num"],
                        "agent_email": data.get("agent_email"),
                        "call_date": data.get("call_date"),
                        "direction": data.get("direction"),
                        "sentiment": data.get("sentiment"),
                        "sector": data.get("sector"),
                        "difficulty_level": data.get("difficulty_level"),
                        "customer_type": data.get("customer_type"),
                        "audio_analysis_commentary": data.get("audio_analysis_commentary", []),
                        "needs": data.get("needs", []),
                        **data.get("audio_features", {}),
                        **embedding_metadata,
                        "created_at": datetime.utcnow().isoformat()
                    }
                )
            ]
        )
    except Exception as e:
        log.exception(f"🚨 Qdrant upsert hatası: {call_id} → {e}")
        return

    try:
        mongo[COLL_SEMANTIC].update_one(
            {"call_id": call_id},
            {"$set": {
                **data,
                "embedding_created_at": datetime.utcnow()
            }},
            upsert=True
        )
    except Exception as e:
        log.exception(f"🚨 Mongo update hatası: {call_id} → {e}")
        return

    try:
        dequeue_semantic(call_id)
    except Exception as e:
        log.warning(f"⚠️ dequeue_semantic hata verdi ama kritik değil: {e}")

    log.info(f"✅ Semantic kayıt tamamlandı: {call_id}")

    try:
        total_semantic_calls = get_total_semantic_count(mongo)
        save_snapshot_if_needed(total_semantic_calls)
    except Exception as e:
        log.warning(f"⚠️ Snapshot alınamadı: {e}")


# ✔ Kuyruktan dinleme
def listen_loop():
    while True:
        try:
            item = rds.blpop(SEMANTIC_QUEUE_KEY, timeout=5)
            if not item:
                continue  # Kuyruk boş
            call_id = item[1].decode()
            log.info(f"🔄 Semantic işleme alındı: {call_id}")
            process_call_id(call_id)
        except Exception as e:
            log.exception(f"🚨 Genel worker hatası: {e}")
            time.sleep(2)


# ✔ Çalıştır
if __name__ == "__main__":
    log.info("📡 Semantic worker başlatıldı. Redis kuyruğu dinleniyor...")
    listen_loop()
