# customer_embedding/customer_sync_worker.py

import logging
from typing import List, Dict, Any, Optional
from pymongo import MongoClient
from customer_embedding.customer_utilts import generate_general_insight_from_customers
from qdrant_client import QdrantClient
import os

# ✔ Logger
log = logging.getLogger("customer_sync_worker")

# ✔ Mongo bağlantısı
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
mongo = MongoClient(MONGO_URI)[MONGO_DB]
COLL_CUSTOMER_VEC = "customer_profiles_rag"
client = QdrantClient(host="qdrant", port=6333)

# ✅ 1. Normal pipeline + collection ile çalışan yapı
def customer_sync_worker(pipeline_or_docs: Any, collection: Optional[str], query: Optional[str] = None) -> Dict[str, Any]:
    """
    Pipeline ya da doğrudan doküman listesi ile LLM analiz çalıştırır.
    Args:
        pipeline_or_docs: Mongo pipeline (List[Dict]) veya doğrudan doküman listesi
        collection: Mongo collection name (pipeline için); docs verilmişse None olabilir
    Returns:
        Dict: LLM çıktısı
    """
    log = logging.getLogger("customer_sync_worker")

    try:
        if collection:
            log.info(f"📡 Mongo aggregate başlatıldı. Collection: {collection}")
            log.info(f"📦 Pipeline:\n{pipeline_or_docs}")
            docs = list(mongo[collection].aggregate(pipeline_or_docs))
        else:
            docs = pipeline_or_docs

        log.info(f"🧾 Toplanan doküman sayısı: {len(docs)}")
       # if len(docs) > 0:
        #    log.info(f"🧾 İlk doküman örneği:\n{docs[0]}")

        if not docs:
            log.warning("⚠️ Analiz için yeterli veri bulunamadı.")
            return {"message": "⚠️ Analiz için yeterli veri bulunamadı."}

        log.info(f"🤖 LLM'e gönderilecek query: {query}")
        llm_output = generate_general_insight_from_customers(docs, query=query)

        log.info(f"📬 LLM'den dönen çıktı: {llm_output}")
        return llm_output

    except Exception as e:
        log.exception("🚨 customer_sync_worker hata:")
        return {"message": f"❌ Genel analiz hatası: {e}"}


# ✅ 2. Fallback: Son N müşteriyi getir
def get_recent_customer_nums(limit: int = 100) -> List[str]:
    """
    Mongo'dan son N müşteri numarasını getirir.
    """
    try:
        pipeline = [
            {"$sort": {"_id": -1}},
            {"$group": {"_id": "$customer_num"}},
            {"$limit": limit}
        ]
        return [doc["_id"] for doc in mongo["audio_jobs"].aggregate(pipeline) if doc["_id"]]
    except Exception as e:
        log.exception("❌ get_recent_customer_nums hata:")
        return []

# ✅ 3. Fallback: customer_nums listesi için benzer müşteri detaylarını getir
def get_similar_customer_details_loop(customer_nums: List[str], top_k=5, threshold=0.75) -> List[Dict[str, Any]]:
    """
    Verilen müşteri numaralarının embedding'leri ile benzer müşteri araması yapar,
    ve detaylı verileri döner.
    """
    try:
        # 1. Mongo’dan embedding’leri al
        docs = list(mongo[COLL_CUSTOMER_VEC].find(
            {"customer_num": {"$in": customer_nums}},
            {"customer_num": 1, "embedding": 1}
        ))

        if not docs:
            log.warning("⚠️ Verilen müşteri numaraları için embedding bulunamadı.")
            return []

        # 2. Her embedding için Qdrant search → benzer customer_num'lar topla
        similar_nums = set()
        for doc in docs:
            vector = doc.get("embedding")
            if not vector:
                continue
            try:
                results = client.search(
                    collection_name=COLL_CUSTOMER_VEC,
                    query_vector=vector,
                    limit=top_k,
                    score_threshold=threshold
                )
                for r in results:
                    if r.payload and "customer_num" in r.payload:
                        similar_nums.add(r.payload["customer_num"])
            except Exception as qerr:
                log.warning(f"⚠️ Qdrant arama hatası: {qerr}")

        if not similar_nums:
            return []

        # 3. Benzer customer_num'lara ait detayları Mongo’dan al
        customer_docs = list(mongo[COLL_CUSTOMER_VEC].find(
            {"customer_num": {"$in": list(similar_nums)}}
        ))

        return customer_docs

    except Exception as e:
        log.exception("❌ get_similar_customer_details_loop hata:")
        return []
