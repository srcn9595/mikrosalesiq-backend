#!/usr/bin/env python3
# reset_customer.py
"""
audio_jobs  ➜  Test amaçlı müşteri analiz sıfırlayıcı
-----------------------------------------------------
• Verilen customer_num için:
    - mini_rag ve analiz verileri silinir
    - calls içindeki her kaydın sadece temel alanları kalır
    - job_status = "queued" olarak güncellenir
    - Tüm müşteri bilgileri ve customer_num korunur
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI   = "mongodb://localhost:27017/"
DB_NAME     = "mikrosalesiq"
COLL_NAME   = "audio_jobs"

client = MongoClient(MONGO_URI)
coll   = client[DB_NAME][COLL_NAME]

def reset_customer_analysis(customer_num: str):
    doc = coll.find_one({"customer_num": customer_num})
    if not doc:
        print(f"❌ Müşteri bulunamadı: {customer_num}")
        return

    print(f"🔁 Sıfırlama başlatıldı: {customer_num}")

    # Yeni "calls" dizisi (yalnızca temel bilgilerle)
    minimal_calls = []
    for call in doc.get("calls", []):
        minimal_calls.append({
            "call_id": call["call_id"],
            "call_key": call.get("call_key"),
            "agent_email": call.get("agent_email"),
            "agent_name": call.get("agent_name"),
            "call_date": call.get("call_date"),
            "direction": call.get("direction"),
            "duration": call.get("duration"),
            "call_result": call.get("call_result"),
            "status": "queued"
        })

    # Temel alanları güncelle (customer_num dahil!)
    update_data = {
        "customer_num": doc["customer_num"],  
        "account_name": doc.get("account_name"),
        "calls": minimal_calls,
        "created_date": doc.get("created_date"),
        "close_date": doc.get("close_date"),
        "contact_email": doc.get("contact_email"),
        "contact_name": doc.get("contact_name"),
        "lead_source": doc.get("lead_source"),
        "lost_reason": doc.get("lost_reason"),
        "lost_reason_detail": doc.get("lost_reason_detail"),
        "opportunity_name": doc.get("opportunity_name"),
        "opportunity_owner": doc.get("opportunity_owner"),
        "opportunity_owner_email": doc.get("opportunity_owner_email"),
        "opportunity_stage": doc.get("opportunity_stage"),
        "product_lookup": doc.get("product_lookup"),
        "job_status": "queued"
    }

    # Analizle ilgili alanları kaldır
    coll.update_one(
        {"_id": doc["_id"]},
        {
            "$set": update_data,
            "$unset": {
                "mini_rag": "",
                "transcript": "",
                "raw_transcript": "",
                "cleaned_transcript": "",
                "audio_features": "",
                "segments": "",
                "audio_analysis_commentary": "",
                "summary": "",
                "risk_score": "",
                "sales_scores": "",
                "token_count": "",
                "sentiment": "",
                "needs": "",
                "difficulty_level": ""
            }
        }
    )

    print(f"✅ {customer_num} başarıyla sıfırlandı.")

# Örnek çalıştırma
if __name__ == "__main__":
    reset_customer_analysis("05011345074")
