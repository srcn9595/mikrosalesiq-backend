#!/usr/bin/env python
# populate_audio_jobs.py — v3.2 (strict agent filter + SF details + phone normalization + call_result)

import re, pymongo
from typing import Optional

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME   = "mikrosalesiq"

cli  = pymongo.MongoClient(MONGO_URI)
db   = cli[DB_NAME]
calls_coll = db["call_records"]
jobs_coll  = db["audio_jobs"]
sf_coll    = db["sf_all_raw"]

# ───────────────────────── Helpers ──────────────────────────────

def norm(phone: Optional[str]) -> Optional[str]:
    """‘+90 5xx…’, ‘905…’, ‘5xx…’ → ‘05xxxxxxxxx’"""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("90"):
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits[0] == "5":
        digits = "0" + digits
    return digits if len(digits) == 11 else None

def aggregate_status(calls):
    states = {c["status"] for c in calls}
    if states == {"done"}: return "done"
    if states <= {"queued"}: return "queued"
    if states <= {"error"}: return "error"
    return "partial"

# ───────────────────────── Ön Hazırlık ──────────────────────────

jobs_coll.create_index("customer_num", unique=True, background=True)
jobs_coll.create_index("calls.call_id", unique=True, background=True)

sf_docs = {norm(doc["contact_phone"]): doc for doc in sf_coll.find() if norm(doc.get("contact_phone"))}
sf_phones = set(sf_docs.keys())
print(f"🎯 SF eşleşebilir numara sayısı: {len(sf_phones):,}")

cursor = calls_coll.find({"duration": {"$gte": 10}})

upserted = 0
for call in cursor:
    inbound = call.get("is_inbound")
    caller  = norm(call.get("caller_id"))
    called  = norm(call.get("called_num"))
    agent   = call.get("agent_email", "").lower()

    # 🚫 Sadece Parasut agent'ları
    if not agent.endswith("@parasut.com") and not agent.endswith("@parasut.com.tr"):
        continue

    # 📞 Hangi numara müşteriye ait
    customer_num = called if called in sf_phones else None
    if not customer_num:
        continue

    # 📄 Call document
    call_doc = {
        "call_id":       call.get("call_id"),
        "call_key":      call.get("call_key"),
        "agent_email":   agent,
        "agent_name":    call.get("agent_name"),
        "call_date":     call.get("call_date"),
        "direction":     "inbound" if inbound else "outbound",
        "duration":      call.get("duration"),
        "call_result":   call.get("status"),  # 'hangup', 'answered', vs.
        "status":        "queued"             # işlenme durumu
    }

    # 🎓 Mevcut çağrıları çek
    doc   = jobs_coll.find_one({"customer_num": customer_num}, {"_id": 0, "calls": 1})
    calls = doc["calls"] if doc else []

    
    if jobs_coll.find_one({"calls.call_id": call_doc["call_id"]}):
        continue

    calls.append(call_doc)
    job_status = aggregate_status(calls)

    # 🧠 SF bilgilerini çek
    sf_info = sf_docs[customer_num]
    sf_fields = {k: sf_info.get(k) for k in [
        "account_name", "contact_name", "contact_email",
        "opportunity_stage", "opportunity_name", "close_date",
        "opportunity_owner", "opportunity_owner_email",
        "lead_source", "lost_reason", "lost_reason_detail",
        "product_lookup", "created_date"
    ]}

    # 📥 Güncelle
    jobs_coll.update_one(
        {"customer_num": customer_num},
        {
            "$set": {
                "calls": calls,
                "job_status": job_status,
                **sf_fields
            },
            "$setOnInsert": {
                "customer_num": customer_num
            }
        },
        upsert=True
    )
    upserted += 1

print(f"✅  Eklenen/güncellenen çağrı sayısı: {upserted:,}")
