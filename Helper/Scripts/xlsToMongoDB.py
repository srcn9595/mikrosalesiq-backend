# This script converts an Excel file to a MongoDB collection.

import re, unicodedata, pymongo, pandas as pd
from datetime import datetime
from typing import Optional

MONGO_URI   = "mongodb://localhost:27017/"
DB_NAME     = "alotech"
COLL_NAME   = "sf_leads_raw"
EXCEL_FILE  = "salesforce_export.xls"          # güncelle

mongo = pymongo.MongoClient(MONGO_URI)
coll  = mongo[DB_NAME][COLL_NAME]

# ───────── yardımcılar ─────────
def ascii_slug(txt: str) -> str:
    no_diac = unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', '_', no_diac).lower()

def to_dt_iso(s: str) -> Optional[str]:     # ← union yerine Optional
    try:
        return datetime.strptime(s, "%d/%m/%Y").isoformat()
    except Exception:
        return None

# ───────── Excel oku ─────────
try:
    df = pd.read_excel(EXCEL_FILE, dtype=str)   # .xlsx veya gerçek .xls
except Exception:
    df = pd.read_html(EXCEL_FILE, flavor="bs4", header=0)[0]
df = df.rename(columns=lambda c: ascii_slug(c.strip()))

# ───────── alan dönüştürmeleri ─────────
df['created_date_raw']    = df['created_date']
df['created_date_iso']    = df['created_date'].apply(to_dt_iso)

df['converted_date_raw']  = df['converted_date']
df['converted_date_iso']  = df['converted_date'].apply(to_dt_iso)

df['phone_raw']           = df['phone']
df['phone_norm']          = df['phone'].str.replace(r'\D', '', regex=True)

# ───────── Mongo’ya upsert ─────────
ops = [
    pymongo.UpdateOne(
        {'parasut_id': row['parasut_id']},       # artık ASCII, boşluk yok
        {'$set': row.to_dict()},
        upsert=True)
    for _, row in df.iterrows()
]

if ops:
    coll.bulk_write(ops, ordered=False)
    print(f"✅ {len(ops):,} lead kaydı yüklendi → {DB_NAME}.{COLL_NAME}")
else:
    print("⚠️  Satır bulunamadı")