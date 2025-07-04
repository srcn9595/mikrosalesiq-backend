# import_salesforce_data.py
import pandas as pd
from pymongo import MongoClient, UpdateOne
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "mikrosalesiq"
COLLECTION_NAME = "sf_all_raw"

# Kaynak dosyalar
FILES = {
    "Closed Won": "opp_won.xlsx",
    "Closed Lost": "opp_lost.xlsx",
    "Lead Lost": "lead_lost.xlsx",
}

# Yardımcı fonksiyonlar
def parse_date(s):
    if pd.isna(s): return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(str(s), fmt)
        except:
            continue
    return None

def normalize_phone(p):
    return ''.join(filter(str.isdigit, str(p))) if pd.notna(p) else None

# Mongo bağlantısı
mongo = MongoClient(MONGO_URI)
col = mongo[DB_NAME][COLLECTION_NAME]
col.create_index(["contact_phone", "opportunity_stage"], background=True)

bulk = []

for stage, file in FILES.items():
    df = pd.read_excel(file)
    for _, row in df.iterrows():
        doc = {
            "opportunity_stage": stage,
            "account_name": row.get("Account Name") or row.get("Company / Account"),
            "opportunity_name": row.get("Opportunity Name"),
            "contact_name": row.get("Primary Contact") or row.get("First Name"),
            "contact_phone": normalize_phone(row.get("Contact: Phone") or row.get("Phone")),
            "contact_email": row.get("Contact: Email") or row.get("Email"),
            "lost_reason": row.get("Lost Reason") or row.get("Lead Lost Reason"),
            "lost_reason_detail": row.get("Lost Reason Detail") or row.get("Lead Lost Reason Detail"),
            "lead_source": row.get("Lead Source"),
            "created_date": parse_date(row.get("Created Date") or row.get("Lead Created Date")),
            "close_date": parse_date(row.get("Close Date") or row.get("Last Modified Date")),
            "opportunity_owner": row.get("Opportunity Owner") or row.get("Lead Owner"),
            "opportunity_owner_email": row.get("Opportunity Owner Email") or row.get("Lead Owner Information"),
            "product_lookup": row.get("Product Lookup"),
        }

        key = {
            "contact_phone": doc["contact_phone"],
            "opportunity_stage": doc["opportunity_stage"]
        }

        bulk.append(UpdateOne(key, {"$set": doc}, upsert=True))

# Batch olarak MongoDB’ye yaz
if bulk:
    result = col.bulk_write(bulk, ordered=False)
    print(f"✅ Tamamlandı: {result.upserted_count} eklendi, {result.modified_count} güncellendi.")
else:
    print("⚠️ Hiç veri eklenmedi.")
