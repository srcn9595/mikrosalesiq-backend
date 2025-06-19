#!/usr/bin/env python
# won_calls_extract.py – v2.1  (duration ≥10 sn)
import pymongo, sys

MONGO_URI = "mongodb://localhost:27017/"
DB        = "mikrosalesiq"

cli   = pymongo.MongoClient(MONGO_URI)
won   = cli[DB]["sf_close_won_raw"]
call  = cli[DB]["call_records"]
out   = cli[DB]["won_calls"]

# ── indeksler ────────────────────────────────────────────────────────────
call.create_index([("caller_id", 1),
                   ("called_num", 1),
                   ("agent_email", 1),
                   ("duration", 1)],  background=True)
out.create_index("call_id", unique=True, background=True)

# ── SF tarafındaki kümeler ───────────────────────────────────────────────
phones = set(won.distinct("contact_phone_norm"))
mails  = set(won.distinct("opportunity_owner_email_norm"))

print(f"Telefon kümesi: {len(phones):>6,}")
print(f"E-posta kümesi:  {len(mails):>6,}")
if not phones or not mails:
    sys.exit("⚠️  Telefon veya mail listesi boş – eşleştirme yapamadım")

# ── inbound + outbound & min duration = 40 sn ────────────────────────────
query = {
    "agent_email": {"$in": list(mails)},
    "duration":    {"$gte": 40},
    "$or": [
        {"caller_id": {"$in": list(phones)}},
        {"called_num": {"$in": list(phones)}}
    ]
}

BATCH = 50_000
processed = inserted = 0
bulk_ops  = []

cursor = call.find(query, no_cursor_timeout=True).batch_size(BATCH)
try:
    for doc in cursor:
        bulk_ops.append(
            pymongo.UpdateOne(
                {"call_id": doc["call_id"]},
                {"$setOnInsert": doc},
                upsert=True
            )
        )
        processed += 1

        if len(bulk_ops) >= BATCH:
            out.bulk_write(bulk_ops, ordered=False)
            inserted += len(bulk_ops)
            bulk_ops.clear()
            print(f"> {processed:,} çağrı tarandı  |  +{inserted:,} yeni", file=sys.stderr)

    if bulk_ops:
        out.bulk_write(bulk_ops, ordered=False)
        inserted += len(bulk_ops)
finally:
    cursor.close()

print(f"✅  Toplam taranan: {processed:,}  |  yeni eklenen: {inserted:,}")
