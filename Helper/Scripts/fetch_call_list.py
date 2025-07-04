#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time, logging, requests, pymongo
from datetime import datetime, timedelta
from typing import Optional                    # ➊ 3.9 uyumu
from dateutil.relativedelta import relativedelta
from pymongo import UpdateOne, ASCENDING

# ──────────── Yapılandırma ────────────
MONGO_URI      = "mongodb://localhost:27017/"
DB_NAME        = "mikrosalesiq"
COLLECTION     = "call_records"
SYNC_COLL      = "sync_state"
SYNC_ID        = "calls_sync"

CLIENT_ID      = "318c1f4a3122049ae812613bc4f1be18"
CLIENT_SECRET  = "274b40f86a8f23a256bd2afc9d4ba428e0dc53c5436e56502263398ebebcd310"
TOKEN_URL      = "https://parasut.alo-tech.com/application/access_token/"
TENANT         = "parasut.alo-tech.com"
API_URL        = "https://api.alo-tech.com/v3/calls"

MIN_SLICE      = timedelta(minutes=15)
START_DT       = datetime(2024, 1, 1)
END_DT         = datetime.now()

# ──────────── MongoDB ────────────
mongo = pymongo.MongoClient(MONGO_URI)
col   = mongo[DB_NAME][COLLECTION]
sync  = mongo[DB_NAME][SYNC_COLL]
col.create_index([("call_key", ASCENDING)], unique=True)

# ──────────── Token Önbelleği ────────────
_token = {"value": None, "expires": datetime.min}

def get_access_token(force: bool = False) -> str:
    if force or datetime.utcnow() >= _token["expires"]:
        r = requests.post(
            TOKEN_URL,
            json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        # ➊  yanıt hangi ismi kullanıyorsa onu oku, yoksa 3600 varsay
        expires_sec = data.get("expires_in") or data.get("duration") or 3600

        _token["value"]   = data["access_token"]
        _token["expires"] = datetime.utcnow() + timedelta(seconds=expires_sec - 30)
        logging.info("🔑  Yeni access token alındı (geçerlilik %s)", _token["expires"])
    return _token["value"]

# ──────────── Sync Yardımcıları ────────────
def load_sync_point() -> Optional[datetime]:    # ➋
    doc = sync.find_one({"_id": SYNC_ID})
    return doc and doc.get("last_dt")

def save_sync_point(last_dt: datetime):
    sync.update_one({"_id": SYNC_ID},
                    {"$set": {"last_dt": last_dt}},
                    upsert=True)

def get_resume_point() -> datetime:
    sp = load_sync_point()
    return sp + timedelta(seconds=1) if sp else START_DT

# ──────────── API İletişimi ────────────
def fetch_calls(start_dt, end_dt, retry=True):
    params = {"start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
              "finish_date": end_dt.strftime("%Y-%m-%d %H:%M:%S")}
    headers = {"Authorization": f"Bearer {get_access_token()}",
               "Tenant": TENANT}

    r = requests.get(API_URL, headers=headers, params=params, timeout=30)

    # token süresi dolduysa
    if r.status_code == 401 and retry:
        logging.warning("401 geldi; token yenileniyor ve tekrar deneniyor")
        get_access_token(force=True)
        return fetch_calls(start_dt, end_dt, retry=False)

    # rate-limit
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "5"))
        logging.warning("429 Too Many Requests → %s sn. bekleniyor", wait)
        time.sleep(wait)
        return fetch_calls(start_dt, end_dt, retry)

    r.raise_for_status()
    return r.json().get("call_details_list", [])

# ──────────── Veri Yazımı ────────────
def _extract_ts(call: dict) -> datetime:
    for fld in ("start_time", "startdatetime", "call_start_time"):
        if fld in call:
            return datetime.fromisoformat(call[fld])
    raise KeyError("Çağrıda zaman damgası alanı bulunamadı")

def store_bulk(calls, slice_end: datetime):
    if not calls:
        return

    # tüm çağrılar için upsert listesi
    ops = [
        UpdateOne({"call_key": call["call_key"]}, {"$set": call}, upsert=True)
        for call in calls
    ]
    col.bulk_write(ops, ordered=False)
    logging.info("💾  %s kayıt kaydedildi", len(calls))

    # dilim başarıyla bitti → bitiş zamanını senkrona yaz
    save_sync_point(slice_end)

# ──────────── Rekürsif Çekim ────────────
def harvest(slice_start, slice_end):
    try:
        calls = fetch_calls(slice_start, slice_end)
    except requests.exceptions.RequestException as e:
        logging.error("İstek hatası (%s). 60 sn sonra tekrar deneniyor", e)
        time.sleep(60)
        return harvest(slice_start, slice_end)

    if len(calls) == 100 and (slice_end - slice_start) > MIN_SLICE:
        mid = slice_start + (slice_end - slice_start) / 2
        harvest(slice_start, mid)
        harvest(mid + timedelta(seconds=1), slice_end)
    else:
        store_bulk(calls, slice_end)   # ⬅️ yeni parametre
        logging.debug("%s → %s : %s kayıt",
                      slice_start.strftime("%F %T"),
                      slice_end.strftime("%F %T"),
                      len(calls))

# ──────────── Ana Döngü ────────────
def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(message)s",
                        datefmt="%H:%M:%S")

    cur = get_resume_point()
    logging.info("🚀 Veri çekimi %s tarihinden itibaren başlıyor", cur)

    while cur < END_DT:
        nxt = min(cur + relativedelta(months=1), END_DT)
        harvest(cur, nxt)
        cur = nxt + timedelta(seconds=1)
        time.sleep(0.25)   # API'ye nazik ol

    logging.info("✅ Tüm aralık (%s → %s) başarıyla işlendi",
                 START_DT.date(), END_DT.date())

if __name__ == "__main__":
    main()
