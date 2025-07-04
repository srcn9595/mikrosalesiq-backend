#!/usr/bin/env python
# enqueue_audio_jobs.py – v2.2  (temiz customer_num mantığı)

import re, pymongo
from typing import Optional   
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME   = "mikrosalesiq"

cli  = pymongo.MongoClient(MONGO_URI)
db   = cli[DB_NAME]
src  = db["won_calls"]          # ≥10 sn süzgecinden geçmiş çağrılar
jobs = db["audio_jobs"]
sf   = db["sf_close_won_raw"]   # referans telefon kümesi

# ───────────────────────── 1) Yardımcılar ───────────────────────────────

def norm(phone: Optional[str]) -> Optional[str]:
    """‘+90 5xx…’, ‘905…’, ‘5xx…’ → ‘05xxxxxxxxx’, aksi takdirde None"""
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
    if states == {"done"}:   return "done"
    if states <= {"queued"}: return "queued"
    if states <= {"error"}:  return "error"
    return "partial"

# ───────────────────────── 2) İndeksler ─────────────────────────────────
jobs.create_index("customer_num",               unique=True, background=True)
jobs.create_index("calls.call_id",              unique=True, background=True)
jobs.create_index("calls.call_date",                            background=True)

# ───────────────────────── 3) SF telefon kümesini çek ──────────────────
sf_phones = {p for p in sf.distinct("contact_phone_norm") if p}
print(f"Salesforce tekil telefon: {len(sf_phones):,}")

# ───────────────────────── 4) Kaynak cursor ────────────────────────────
fields = {
    "_id": 0,
    "caller_id":   1,
    "called_num":  1,
    "is_inbound":  1,
    "agent_email": 1,
    "call_key": 1,
    "call_id":     1,
    "call_date":   1
}
cursor   = src.find({}, fields)
upserted = 0

for rec in cursor:
    # --- müşteri numarasını seç ---
    inbound  = rec.get("is_inbound")
    caller   = norm(rec.get("caller_id"))
    called   = norm(rec.get("called_num"))

    if inbound is True:
        customer_num = caller
    elif inbound is False:
        customer_num = called
    else:                               # None → hangi uç SF kümesindeyse o
        customer_num = caller if caller in sf_phones else called
    if customer_num not in sf_phones:       # hâlâ yoksa atla
        continue

    # --- çağrı dokümanı ---
    call_doc = {
        "call_id":         rec["call_id"],
        "call_key":        rec["call_key"],
        "agent_email":     rec["agent_email"],
        "call_date":       rec["call_date"],
        "direction":       "inbound" if inbound else "outbound",
        "status":          "queued"
    }

    # --- mevcut belgeyi al; yoksa boş liste ---
    doc   = jobs.find_one({"customer_num": customer_num}, {"_id": 0, "calls": 1})
    calls = doc["calls"] if doc else []

    # aynı call_id daha önce eklendiyse geç
    if any(c["call_id"] == call_doc["call_id"] for c in calls):
        continue

    calls.append(call_doc)
    job_status = aggregate_status(calls)

    jobs.update_one(
        {"customer_num": customer_num},
        {
            "$set":  {"calls": calls, "job_status": job_status},
            "$setOnInsert": {"customer_num": customer_num}
        },
        upsert=True
    )
    upserted += 1

print(f"✅  Eklenen/güncellenen çağrı sayısı: {upserted:,}")
