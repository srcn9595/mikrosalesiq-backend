#!/usr/bin/env python
# cleanup_after_mini_rag.py – v1.1
import pymongo, sys, argparse
from datetime import datetime
import copy

MONGO_URI = "mongodb://localhost:27017/"
DB        = "mikrosalesiq"
COLL      = "audio_jobs"
BATCH     = 5000

cli   = pymongo.MongoClient(MONGO_URI)
coll = cli[DB][COLL]

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Veritabanına yazma, sadece kaç tane doküman etkilenecek göster.")
parser.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum doküman sayısı")
args = parser.parse_args()

def clean_calls(calls):
    keys_to_delete = [
        "segments", "error",
        "retry_count", "transcribed_at", "cleaned_at", "downloaded_at","status"
    ]
    updated = []
    for c in calls:
        if not c or not isinstance(c, dict):
            continue
        for k in keys_to_delete:
            c.pop(k, None)
        updated.append(c)
    return updated

query = {"mini_rag": {"$exists": True}}
cursor = coll.find(query, no_cursor_timeout=True).batch_size(BATCH)

cleaned = modified = 0
bulk_ops = []

try:
    for doc in cursor:
        if args.limit and cleaned >= args.limit:
            break

        _id = doc["_id"]
        original_calls = doc.get("calls", [])
        original_copy  = copy.deepcopy(original_calls)  # 🔒 orijinali tut
        new_calls      = clean_calls(original_calls)    # temizleme yapılacak

        if new_calls != original_copy:  # ✅ karşılaştırma artık doğru çalışır
            modified += 1
            if not args.dry_run:
                bulk_ops.append(pymongo.UpdateOne({"_id": _id}, {"$set": {"calls": new_calls}}))

        cleaned += 1

        if not args.dry_run and len(bulk_ops) >= BATCH:
            coll.bulk_write(bulk_ops, ordered=False)
            print(f"> {cleaned:,} tarandı | +{modified:,} güncellendi", file=sys.stderr)
            bulk_ops.clear()

    if not args.dry_run and bulk_ops:
        coll.bulk_write(bulk_ops, ordered=False)

finally:
    cursor.close()

print(f"🧹 Bitti – Taranan: {cleaned:,} | Güncellenen: {modified:,} | Dry-run: {args.dry_run}")
