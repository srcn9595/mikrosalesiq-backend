#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
full_random_dump.py
-------------------
Koleksiyondan alan filtresi yapmadan rastgele N belge alır,
JSON Lines (isteğe bağlı .gz) olarak kaydeder.
"""

import argparse, gzip, json, datetime as dt
from pymongo import MongoClient
from bson import json_util       # Mongo tipi (ObjectId, datetime, …) serileştirmek için

# ─────── CLI ───────
ap = argparse.ArgumentParser()
ap.add_argument("--mongo", default="mongodb://localhost:27017")
ap.add_argument("--db",    default="alotech")
ap.add_argument("--coll",  default="call_records")
ap.add_argument("-n", "--nsample", type=int, default=1_000,
                help="Kaç rastgele belge?")
ap.add_argument("--out", default="full_sample_{{date}}.jsonl.gz",
                help="Çıktı dosyası ({{date}} bugünle değişir)")
ap.add_argument("--nogzip", action="store_true",
                help="Sıkıştırma kapatılsın mı?")
args = ap.parse_args()

out_file = args.out.replace("{{date}}", dt.date.today().isoformat())
if args.nogzip and out_file.endswith(".gz"):
    out_file = out_file[:-3]           # uzantı düzelt

# ─────── Mongo ───────
cli  = MongoClient(args.mongo)
coll = cli[args.db][args.coll]

print(f"⏳  $sample size={args.nsample} …")
cursor = coll.aggregate([{"$sample": {"size": args.nsample}}])

# ─────── Yazım ───────
open_fn = gzip.open if (out_file.endswith(".gz") and not args.nogzip) else open
with open_fn(out_file, "wt", encoding="utf-8") as f:
    for doc in cursor:
        f.write(json_util.dumps(doc, ensure_ascii=False) + "\n")

print(f"✅  {args.nsample} belge → {out_file}")
