#!/usr/bin/env python
import re, unicodedata, pymongo, pandas as pd
from datetime import datetime
from typing import Optional
# ─────── AYARLAR ───────
MONGO_URI   = "mongodb://localhost:27017/"
DB_NAME     = "mikrosalesiq"
COLL_NAME   = "sf_close_won_raw"       # ← aynı adı kullanalım
EXCEL_FILE  = "close_won.xlsx"         # *.xlsx olduğundan openpyxl yeter

mongo = pymongo.MongoClient(MONGO_URI)
coll  = mongo[DB_NAME][COLL_NAME]

# ─────── Excel oku ───────
df = pd.read_excel(EXCEL_FILE, dtype=str)   # openpyxl otomatik seçilir

# ── 1) Başlıkları sadeleştir ──
def slug(x: str) -> str:
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
    x = re.sub(r"\s+", "_", x.strip().lower())
    return re.sub(r"[^0-9a-z_]", "", x)

df.columns = [slug(c) for c in df.columns]      # artık contact_phone vs.

# ── 2) Tarih kolonlarını ISO-8601 + raw ──
def to_iso(s: str):
    try:
        return datetime.strptime(str(s), "%d/%m/%Y").isoformat()
    except Exception:
        return None

for col in ("close_date", "created_date"):
    if col in df.columns:
        df[f"{col}_iso"] = df[col].apply(to_iso)
        df[f"{col}_raw"] = df[col]

def norm_phone(raw: Optional[str]) -> Optional[str]:
    """
    Telefona ait her türlü girdiyi 0XXXXXXXXXX (11 hane) biçimine çevirir.
    Hatalı/eksik numara varsa None döner.
    """
    # 1) NaN, None, boş hücre → None
    if pd.isna(raw) or raw is None:
        return None

    # 2) String'e dönüştür, rakam dışı her şeyi temizle
    digits = re.sub(r"\D", "", str(raw))

    # 3) +90 / 90 önekini at
    if digits.startswith("90"):
        digits = digits[2:]

    # 4) Başında 0 yoksa ekle (10 hanelik ise)
    if len(digits) == 10:
        digits = "0" + digits

    # 5) Son kontrol: 11 hane, 0 ile başlıyor mu?
    return digits if (len(digits) == 11 and digits.startswith("0")) else None


if "contact_phone" in df.columns:
    df["contact_phone_raw"]  = df["contact_phone"]
    df["contact_phone_norm"] = df["contact_phone"].apply(norm_phone)

# ── 4) (Opsiyonel) agent email’i normalize et ──
if "opportunity_owner_email" in df.columns:
    df["opportunity_owner_email_norm"] = df["opportunity_owner_email"].str.lower().str.strip()

# ── 5) Mongo’ya toplu insert ──
records = df.to_dict("records")
if records:
    coll.insert_many(records)          # **unique key yok** → tamamı insert
    print(f"✅  {len(records):,} satır eklendi → {DB_NAME}.{COLL_NAME}")
else:
    print("⚠️  Eklenecek satır yok")

# ── 6) Hız için index – sadece ilk sefer çalışır ──
coll.create_index("contact_phone_norm")
coll.create_index("opportunity_owner_email_norm")
