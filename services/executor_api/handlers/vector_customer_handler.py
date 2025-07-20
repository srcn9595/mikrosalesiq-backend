from qdrant_client import QdrantClient
import os
import json
from customer_embedding.embedding_utilts import get_customer_embedding as get_embedding
from customer_embedding.customer_sync_worker import (
    customer_sync_worker,
    get_recent_customer_nums,
    get_similar_customer_details_loop
)
import logging

client = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", "6333"))
)
log = logging.getLogger("vector_customer_handler")


def format_vector_customer_output(raw: dict) -> dict:
    return {
        "summary": raw.get("summary", ""),
        "recommendations": raw.get("recommendations", []),
        "customer_profile": raw.get("customer_profile", {}),
        "audio_analysis": raw.get("audio_analysis", {}),
        "sales_scores": raw.get("sales_scores", {}),
        "next_steps": raw.get("next_steps", []),
        "conversion_probability": raw.get("conversion_probability"),
        "risk_score": raw.get("risk_score"),
        "common_issues": raw.get("common_issues", []),
        "strengths": raw.get("strengths", []),
        "segments": raw.get("segments", []),
        "agent_improvements": raw.get("agent_improvements", []),
        "high_potential_customers": raw.get("high_potential_customers", []),
        "note": raw.get("note", "")
    }


async def vector_customer_handler(args: dict):
    query = args.get("query", "").strip()
    top_k = args.get("top_k", 10)
    threshold = 0.35
    embedding_type = args.get("embedding_type", "customer_level")
    pipeline = args.get("pipeline", [])
    collection = args.get("collection", "audio_jobs")

    try:
        log.info(f"🧠 Sorgu alındı: '{query}' | pipeline: {pipeline}")

        # 1️⃣ Embed üret
        vector = get_embedding(query)
        log.info(f"🧱 Vektör üretildi mi?: {'Evet' if vector else 'Hayır'}")

        if vector:
            log.info(f"➡️ Embedding query: {query}")
            log.info(f"➡️ Embed result (ilk 5): {vector[:5]}...")

            search_result = client.search(
                collection_name="customer_profiles",
                query_vector=vector,
                limit=top_k,
                score_threshold=threshold
            )

            log.info(f"➡️ Qdrant result count: {len(search_result)}")

            similarity_output = [r.dict() for r in search_result]
            log.debug(f"📦 Qdrant raw output: {similarity_output}")

            customer_nums = [
                r["payload"]["customer_num"]
                for r in similarity_output
                if "payload" in r and "customer_num" in r["payload"]
            ]
            log.info(f"🧾 Elde edilen müşteri numaraları: {customer_nums}")

            if not customer_nums:
                log.warning("🔍 Uygun müşteri numarası bulunamadı (Qdrant içinde).")
                return {
                    "name": "vector_customer",
                    "output": {
                        "items": [],
                        "note": "🔍 Uygun müşteri numarası bulunamadı."
                    }
                }

            # 2️⃣ Mongo pipeline'a ekle
            customer_filter = {
                "$match": {
                    "customer_num": {"$in": customer_nums}
                }
            }

            match_updated = False
            for stage in pipeline:
                if "$match" in stage and "customer_num" in stage["$match"]:
                    match_expr = stage["$match"]["customer_num"]
                    if isinstance(match_expr, dict) and "$in" in match_expr:
                        match_expr["$in"] = customer_nums
                        match_updated = True
                        break

            if not match_updated:
                pipeline = [customer_filter] + pipeline

            if "conversion_probability" in json.dumps(pipeline) and len(customer_nums) <= 3:
                log.warning("⚠️ Çok az eşleşme, pipeline filtresi kaldırıldı.")
                pipeline = [{"$match": {"customer_num": {"$in": customer_nums}}}]

            log.info(f"🔧 Final Mongo Pipeline: {pipeline}")

            # 3️⃣ LLM çağrısı
            llm_output = customer_sync_worker(pipeline, collection, query=query)

            if isinstance(llm_output, str):
                try:
                    llm_output = json.loads(llm_output)
                except json.JSONDecodeError as e:
                    log.warning(f"⚠️ LLM çıktısı parse edilemedi: {e}")
                    return {
                        "name": "vector_customer",
                        "output": {
                            "items": [],
                            "note": f"❌ LLM JSON parse hatası: {e}"
                        }
                    }

            if "summary" not in llm_output:
                log.warning(f"⚠️ LLM çıktısı beklenen formatta değil: {llm_output}")
                return {
                    "name": "vector_customer",
                    "output": {
                        "items": [],
                        "note": "⚠️ LLM çıktısı geçersiz: summary alanı yok."
                    }
                }

            formatted = format_vector_customer_output(llm_output)
            log.info("✅ LLM çıktısı başarıyla işlendi.")
            return {
                "name": "vector_customer",
                "output": {
                    "items": [formatted]
                }
            }

        # 4️⃣ Fallback (query yoksa)
        log.warning("❗ Anlamlı vektör yok, fallback başlatılıyor.")
        recent_customer_nums = get_recent_customer_nums(limit=100)
        log.info(f"📚 Son 100 müşteri alındı: {len(recent_customer_nums)} adet")

        if not recent_customer_nums:
            log.error("❌ Fallback başlatılamadı, müşteri numarası alınamadı.")
            return {
                "name": "vector_customer",
                "output": {
                    "items": [],
                    "note": "⚠️ Fallback başlatılamadı, müşteri numarası bulunamadı."
                }
            }

        customer_docs = get_similar_customer_details_loop(
            customer_nums=recent_customer_nums,
            top_k=top_k,
            threshold=threshold
        )
        log.info(f"📦 Fallback ile benzer müşteri detayları bulundu: {len(customer_docs)}")

        if not customer_docs:
            return {
                "name": "vector_customer",
                "output": {
                    "items": [],
                    "note": "⚠️ Fallback ile bile anlamlı müşteri verisi bulunamadı."
                }
            }

        llm_output = customer_sync_worker(customer_docs, collection=None, query=query)
        log.info("✅ Fallback LLM çıktısı başarıyla alındı.")

        formatted = format_vector_customer_output({
            **llm_output,
            "note": "Query anlamsız olduğu için fallback (son müşterilerden benzer grup) kullanıldı."
        })

        return {
            "name": "vector_customer",
            "output": {
                "items": [formatted]
            }
        }

    except Exception as e:
        log.exception("❌ vector_customer_handler sırasında hata oluştu:")
        return {
            "name": "vector_customer",
            "output": {
                "items": [],
                "note": f"❌ Handler sırasında hata: {e}"
            }
        }
