# customer_embedding_worker.py

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
from uuid import uuid5, NAMESPACE_DNS

from customer_embedding.embedding_utilts import get_customer_embedding, get_embedding_metadata
from customer_embedding.snapshot_manager import get_total_customer_count, save_snapshot_if_needed
from queue_utils import dequeue_customer_embedding

# ✔ Ortam değişkenleri
REDIS_URL           = os.getenv("REDIS_URL", "redis://localhost:6379")
MONGO_URI           = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB            = os.getenv("MONGO_DB", "mikrosalesiq")
COLL_AUDIO          = "audio_jobs"
COLL_CUSTOMER_VEC   = "customer_profiles_rag"
QDRANT_HOST         = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT         = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION   = "customer_profiles"

# ✔ Bağlantılar
rds     = redis.from_url(REDIS_URL)
mongo   = pymongo.MongoClient(MONGO_URI)[MONGO_DB]
qdrant  = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# ✔ Logger
log = logging.getLogger("customer_embedding_worker")
logging.basicConfig(level=logging.INFO)

# ✔ Redis kuyruk ismi
CUSTOMER_QUEUE_KEY = "customer_embedding_jobs"

# ✔ Yardımcı fonksiyon
def get_customer_input(customer_num: str) -> Optional[dict]:
    doc = mongo[COLL_AUDIO].find_one({"customer_num": customer_num})
    if not doc:
        log.warning(f"❌ Müşteri bulunamadı: {customer_num}")
        return None

    mini_rag = doc.get("mini_rag", {})
    profile = mini_rag.get("customer_profile", {})
    merged_transcript = mini_rag.get("merged_transcript")
    summary = mini_rag.get("summary")

    if not profile or not merged_transcript:
        log.warning(f"⚠️ Veri eksik: {customer_num}")
        return None

    return {
        # Anahtar alanlar
        "customer_num": customer_num,
        "summary": summary,
        "merged_transcript": merged_transcript,

        # 🧠 Profil bilgileri (mini_rag.customer_profile)
        "sector": profile.get("sector"),
        "role": profile.get("role"),
        "personality_type": profile.get("personality_type"),
        "zorluk_seviyesi": profile.get("zorluk_seviyesi"),
        "müşteri_kaynağı": profile.get("müşteri_kaynağı"),
        "inceleme_durumu": profile.get("inceleme_durumu"),
        "needs": profile.get("needs", []),

        # 📊 CRM verileri (ana seviyeden)
        "opportunity_name": doc.get("opportunity_name"),
        "opportunity_stage": doc.get("opportunity_stage"),
        "opportunity_owner": doc.get("opportunity_owner"),
        "opportunity_owner_email": doc.get("opportunity_owner_email"),
        "contact_name": doc.get("contact_name"),
        "contact_email": doc.get("contact_email"),
        "lead_source": doc.get("lead_source"),
        "lost_reason": doc.get("lost_reason"),
        "lost_reason_detail": doc.get("lost_reason_detail"),
        "product_lookup": doc.get("product_lookup"),
        "job_status": doc.get("job_status"),

        # 📅 Tarihsel alanlar (string olarak)
        "created_date": str(doc.get("created_date")) if doc.get("created_date") else None,
        "close_date": str(doc.get("close_date")) if doc.get("close_date") else None,
    }

# ✔ Ana işleme fonksiyonu
def process_customer(customer_num: str):
    data = get_customer_input(customer_num)
    if not data:
        return

    embedding = get_customer_embedding(data["merged_transcript"])
    if not embedding:
        log.error(f"❌ Embedding alınamadı: {customer_num}")
        return

    try:
        collections = [c.name for c in qdrant.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            log.info(f"📁 Koleksiyon oluşturuluyor: {QDRANT_COLLECTION}")
            qdrant.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )

        point_id = str(uuid5(NAMESPACE_DNS, customer_num))
        payload = {
            **data,
            **get_embedding_metadata(),
            "created_at": datetime.utcnow().isoformat()
        }

        qdrant.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[PointStruct(id=point_id, vector=embedding, payload=payload)]
        )

        mongo[COLL_CUSTOMER_VEC].update_one(
            {"customer_num": customer_num},
            {"$set": {**data, "embedding_created_at": datetime.utcnow()}},
            upsert=True
        )

        dequeue_customer_embedding(customer_num)
        log.info(f"✅ Embedding tamamlandı: {customer_num}")

        # ✔ Snapshot kontrol
        try:
            total = get_total_customer_count(mongo)
            save_snapshot_if_needed(total)
        except Exception as e:
            log.warning(f"⚠️ Snapshot alınamadı: {e}")

    except Exception as e:
        log.exception(f"🚨 Hata oluştu ({customer_num}): {e}")

# ✔ Kuyruktan dinleme
def listen_loop():
    while True:
        try:
            item = rds.blpop(CUSTOMER_QUEUE_KEY, timeout=5)
            if not item:
                continue
            customer_num = item[1].decode()
            log.info(f"🔄 İşlem başlatıldı: {customer_num}")
            process_customer(customer_num)
        except Exception as e:
            log.exception(f"🔥 Genel worker hatası: {e}")
            time.sleep(2)

if __name__ == "__main__":
    log.info("🚀 Customer embedding worker başlatıldı.")
    listen_loop()
