"""
customer_embedding_worker.py
----------------------------
Müşteri bazlı embedding üreten worker'ın **sağlam** ve **sonsuz döngüye girmeyen** sürümü.
Değişiklikler:
• `get_customer_input()` döndürdüğü sözlüğe `mini_rag` eklendi ⇒ KeyError kalktı.
• Embedding hata verse bile kuyruğu tıkamamak için `dequeue_customer_embedding` artık `finally` bloğunda.
• Daha anlaşılır log mesajları + seviye ayarı.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional
from uuid import uuid5, NAMESPACE_DNS

import pymongo
import redis
from bson.objectid import ObjectId  # şimdilik tutuluyor, ileride gerekiyorsa kullanılır
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Distance, VectorParams

from customer_embedding.embedding_utilts import (
    get_customer_embedding,
    get_embedding_metadata,
)
from customer_embedding.snapshot_manager import (
    get_total_customer_count,
    save_snapshot_if_needed,
)
from queue_utils import dequeue_customer_embedding

# ───────────────────────────── ENV & CONST ─────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")

COLL_AUDIO = "audio_jobs"
COLL_CUSTOMER_VEC = "customer_profiles_rag"

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION = "customer_profiles"

CUSTOMER_QUEUE_KEY = "customer_embedding_jobs"

# ───────────────────────────── Clients ─────────────────────────────
rds = redis.from_url(REDIS_URL)
mongo = pymongo.MongoClient(MONGO_URI)[MONGO_DB]
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# ───────────────────────────── Logging ─────────────────────────────
log = logging.getLogger("customer_embedding_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ───────────────────────────── Helpers ─────────────────────────────

def get_customer_input(customer_num: str) -> Optional[dict]:
    """Mongo'dan mini_rag'i ve gerekli CRM alanlarını toplar."""
    doc = mongo[COLL_AUDIO].find_one({"customer_num": customer_num})
    if not doc:
        log.warning("❌ Müşteri bulunamadı: %s", customer_num)
        return None

    mini_rag = doc.get("mini_rag", {})
    profile = mini_rag.get("customer_profile", {})
    if not profile:  # profil yoksa görece eksik veri, kuyruğa geri koymayalım
        log.warning("⚠️ mini_rag.profile eksik: %s", customer_num)
        return None

    return {
        "customer_num": customer_num,
        "mini_rag": mini_rag,  # 🔑 EKLENDİ – diğer fonksiyonlar doğrudan kullanıyor
        "summary": mini_rag.get("summary"),
        "merged_transcript": mini_rag.get("merged_transcript"),

        # 🧠 Profil bilgileri
        "sector": profile.get("sector"),
        "role": profile.get("role"),
        "personality_type": profile.get("personality_type"),
        "zorluk_seviyesi": profile.get("zorluk_seviyesi"),
        "müşteri_kaynağı": profile.get("müşteri_kaynağı"),
        "inceleme_durumu": profile.get("inceleme_durumu"),
        "needs": profile.get("needs", []),

        # 📊 CRM alanları
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

        # 📅 Tarihsel alanlar
        "created_date": str(doc.get("created_date")) if doc.get("created_date") else None,
        "close_date": str(doc.get("close_date")) if doc.get("close_date") else None,
    }


def build_embedding_input_from_mini_rag(mini_rag: dict) -> str:
    """mini_rag sözlüğünü tek satırlık, zengin bir doğal dil girdisine dönüştürür."""

    profile = mini_rag.get("customer_profile", {})
    recommendations = mini_rag.get("recommendations", [])
    summary = mini_rag.get("summary", "")
    risk = mini_rag.get("risk_score", "")
    sales = mini_rag.get("sales_scores", {})
    next_steps = mini_rag.get("next_steps", {})
    analysis = mini_rag.get("audio_analysis", {}).get("audio_analysis_commentary", [])
    audio_summary = mini_rag.get("audio_features_summary", {})
    sentiment = mini_rag.get("sentiment", "") or mini_rag.get("audio_analysis", {}).get("sentiment", "")
    emotion_shift = mini_rag.get("emotion_shift_score", "") or audio_summary.get("emotion_shift_score", "")
    conversion_prob = mini_rag.get("conversion_probability", "")
    confidence = mini_rag.get("confidence", "")

    text = f"""
📄 Özet: {summary}
🧠 Profil: {json.dumps(profile, ensure_ascii=False)}
💡 Öneriler: {', '.join(recommendations)}
⚠️ Risk Skoru: {risk}
📈 Satış Skorları: {json.dumps(sales, ensure_ascii=False)}
🎯 Sonraki Adımlar (Müşteri): {', '.join(next_steps.get('for_customer', []))}
🎯 Sonraki Adımlar (Temsilci): {', '.join(next_steps.get('for_agent', []))}
🔈 Sesli Analiz Yorumu: {', '.join(analysis)}
🎵 Audio Özellikleri: {json.dumps(audio_summary, ensure_ascii=False)}
🎭 Duygu Geçiş Skoru: {emotion_shift}
❤️ Duygu Durumu: {sentiment}
🎯 Dönüşüm Olasılığı: {conversion_prob}
📊 Güven Skoru: {confidence}
"""
    return text.strip()


# ───────────────────────────── Core worker ─────────────────────────────

def process_customer(customer_num: str) -> None:
    """Tek bir müşteri numarası için embedding üretir ve sisteme kaydeder."""

    data = get_customer_input(customer_num)
    if not data:
        return  # veri eksik → kuyrukta tutma, şimdilik yoksay

    try:
        embedding_input = build_embedding_input_from_mini_rag(data["mini_rag"])
        embedding = get_customer_embedding(embedding_input)
        if not embedding:
            log.error("❌ Embedding alınamadı: %s", customer_num)
            return

        # Koleksiyon var mı?
        if QDRANT_COLLECTION not in [c.name for c in qdrant.get_collections().collections]:
            log.info("📁 Qdrant koleksiyonu oluşturuluyor: %s", QDRANT_COLLECTION)
            qdrant.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )

        point_id = str(uuid5(NAMESPACE_DNS, customer_num))
        payload = {
            **data,
            **get_embedding_metadata(),
            "created_at": datetime.utcnow().isoformat(),
        }

        qdrant.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[PointStruct(id=point_id, vector=embedding, payload=payload)],
        )

        mongo[COLL_CUSTOMER_VEC].update_one(
            {"customer_num": customer_num},
            {"$set": {**data, "embedding_created_at": datetime.utcnow()}},
            upsert=True,
        )

        log.info("✅ Embedding tamamlandı → %s", customer_num)

        # Snapshot
        try:
            total = get_total_customer_count(mongo)
            save_snapshot_if_needed(total)
        except Exception as snap_err:
            log.warning("⚠️ Snapshot alınamadı: %s", snap_err)

    except Exception as e:
        log.exception("🚨 Embedding işlemi patladı (%s): %s", customer_num, e)

    finally:
        # Başarılı olsun olmasın, bu customer numarasını aktif kuyruktan çıkar
        try:
            dequeue_customer_embedding(customer_num)
        except Exception as del_err:
            log.warning("⚠️ Kuyruktan silme hatası (%s): %s", customer_num, del_err)


# ───────────────────────────── Main loop ─────────────────────────────

def listen_loop() -> None:
    log.info("🚀 Customer embedding worker dinlemede…")
    while True:
        try:
            item = rds.blpop(CUSTOMER_QUEUE_KEY, timeout=5)
            if not item:
                continue
            customer_num = item[1].decode()
            log.info("🔄 İşlem başlatıldı → %s", customer_num)
            process_customer(customer_num)
        except Exception as loop_err:
            log.exception("🔥 Genel worker hatası: %s", loop_err)
            time.sleep(2)


if __name__ == "__main__":
    listen_loop()
