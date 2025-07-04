#!/usr/bin/env python3
"""download_recordings.py

Alotech API’den ses kayıtlarını indirip **audio_jobs** koleksiyonundaki
çağrı nesnelerinin durumunu günceller.

Çalışma akışı
-------------
1. **audio_jobs** → *queued* durumundaki alt‑çağrılar FIFO olarak çekilir.
2.   /v3/calls/{call_key}/recordings  uç noktası çağrılır.
3.   İndirilen WAV dosyası  recordings/<customer_num>/YYYY‑MM‑DD_HH‑MM‑SS_<call_id>.wav
     şeklinde kaydedilir.
4.   Alt‑çağrı **downloaded** yapılır; üst belgedeki *job_status* alanı da
     *queued / partial / downloaded* olarak yeniden hesaplanır.

Komut satırı
------------
    python download_recordings.py --limit 25   # aynı seferde en fazla 25 dosya

Limit verilmezse varsayılan **10** tur.
"""

from __future__ import annotations   # ⟵ get rid of `|` typing issues
import argparse, os, pathlib, time, logging, requests, pymongo, re
from datetime import datetime, timedelta
from pymongo import ASCENDING, UpdateOne
from typing import Optional, List

# ───── Sabitler ──────────────────────────────────────────────────────────
MONGO_URI   = "mongodb://localhost:27017/"
DB_NAME     = "alotech"
JOBS_COLL   = "audio_jobs"

CLIENT_ID      = "318c1f4a3122049ae812613bc4f1be18"
CLIENT_SECRET  = "274b40f86a8f23a256bd2afc9d4ba428e0dc53c5436e56502263398ebebcd310"
TOKEN_URL      = "https://parasut.alo-tech.com/application/access_token/"
TENANT         = "parasut.alo-tech.com"
REC_API        = "https://parasut.alo-tech.com/v3/calls/{key}/recordings"

DOWNLOAD_ROOT  = pathlib.Path("recordings")
TIME_FMT       = "%Y-%m-%d_%H-%M-%S"

# ───── Global token önbelleği ───────────────────────────────────────────
_token_val: Optional[str] = None
_token_expires: datetime  = datetime.min

def get_access_token(force: bool = False) -> str:
    """OAuth token’ı döndürür; süresi dolmuşsa yeniler."""
    global _token_val, _token_expires

    if force or datetime.utcnow() >= _token_expires:
        resp = requests.post(
            TOKEN_URL,
            json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        _token_val = payload["access_token"]
        ttl = payload.get("expires_in") or payload.get("duration") or 3600
        _token_expires = datetime.utcnow() + timedelta(seconds=ttl - 30)
        logging.info("🔑  Yeni token alındı (exp %s)", _token_expires)
    return _token_val  # pyright: ignore[return-value]

# ───── Yardımcılar ──────────────────────────────────────────────────────

def aggregate_status(calls: List[dict]) -> str:
    states = {c["status"] for c in calls}
    if states == {"downloaded"}:
        return "downloaded"
    if states <= {"queued"}:
        return "queued"  # hepsi queued
    if "downloaded" in states:
        return "partial"
    return "error"


def fetch_recording(call_key: str, headers: dict, retry: bool = True) -> bytes:
    """Alotech kayıt API’sinden sesi indirir (gerekirse presigned URL’e atlar)."""
    url = REC_API.format(key=call_key)
    r = requests.get(url, headers=headers, params={"copy_recording": "false"}, timeout=60)

    if r.status_code == 401 and retry:
        headers["Authorization"] = f"Bearer {get_access_token(force=True)}"
        return fetch_recording(call_key, headers, retry=False)

    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "5"))
        logging.warning("429 Too Many Requests – %s sn bekleniyor", wait)
        time.sleep(wait)
        return fetch_recording(call_key, headers, retry)

    r.raise_for_status()

    # İçeriğin gerçekten ses olup olmadığını anlamak için Content-Type'e daha geniş bak
    ctype = r.headers.get("content-type", "")
    if "audio" in ctype or "octet-stream" in ctype:
        return r.content  # WAV veya benzeri bir dosya

    try:
        data = r.json()
        link = data.get("url") or data.get("recording_url")
        if not link:
            raise RuntimeError("Kayıt URL’i bulunamadı (JSON içinde)")
        a = requests.get(link, timeout=60)
        a.raise_for_status()
        return a.content
    except Exception as e:
        raise RuntimeError(f"Beklenmeyen yanıt: {r.text[:200]}... ({e})")


def get_customers_with_queued_calls(limit: int) -> List[str]:
    """call_date'e göre sırayla queued çağrıları olan ilk N müşteriyi getir."""
    pipeline = [
        {"$unwind": "$calls"},
        {"$match": {"calls.status": "queued"}},
        {"$sort": {"calls.call_date": 1}},
        {"$group": {
            "_id": "$customer_num"
        }},
        {"$limit": limit}
    ]
    results = list(jobs.aggregate(pipeline))
    return [doc["_id"] for doc in results]

# ───── Ana İşlev ────────────────────────────────────────────────────────
def main(limit: int = 1):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    global jobs
    cli   = pymongo.MongoClient(MONGO_URI)
    jobs  = cli[DB_NAME][JOBS_COLL]

    headers = {
        "Tenant": TENANT,
        "Authorization": f"Bearer {get_access_token()}",
    }

    customer_nums = get_customers_with_queued_calls(limit)
    if not customer_nums:
        logging.info("İndirilecek müşteri bulunamadı (queued = 0)")
        return

    total_downloaded = 0

    for customer in customer_nums:
        doc = jobs.find_one({"customer_num": customer})
        if not doc:
            continue

        downloaded = 0
        for call in doc.get("calls", []):
            if call.get("status") != "queued":
                continue

            try:
                ts = datetime.strptime(call["call_date"], "%Y-%m-%d %H:%M:%S")
                fname = f"{ts.strftime(TIME_FMT)}_{call['call_id']}.wav"
                fpath = DOWNLOAD_ROOT / customer / fname

                audio = fetch_recording(call["call_key"], headers)
                fpath.parent.mkdir(parents=True, exist_ok=True)
                with fpath.open("wb") as fp:
                    fp.write(audio)

                jobs.update_one(
                    {"customer_num": customer, "calls.call_id": call["call_id"]},
                    {"$set": {
                        "calls.$.status": "downloaded",
                        "calls.$.file_path": str(fpath),
                        "calls.$.downloaded_at": datetime.utcnow(),
                    }}
                )

                downloaded += 1

            except Exception as exc:
                logging.error("✗ %s %s  (%s)", customer, call["call_id"], exc)
                jobs.update_one(
                    {"customer_num": customer, "calls.call_id": call["call_id"]},
                    {"$set": {"calls.$.status": "error", "calls.$.error": str(exc)}}
                )

        # Çağrıların durumu güncellenip iş bitti, şimdi job_status yeniden hesapla
        updated = jobs.find_one({"customer_num": customer}, {"calls.status": 1})
        jobs.update_one(
            {"customer_num": customer},
            {"$set": {"job_status": aggregate_status(updated["calls"])}}
        )

        total_downloaded += downloaded
        logging.info("📦  %s müşterisinden indirilen kayıt sayısı: %d", customer, downloaded)

    logging.info("✅  Toplam indirilen dosya sayısı: %s", total_downloaded)
# ───── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    argp = argparse.ArgumentParser(description="audio_jobs → WAV indirici")
    argp.add_argument("--limit", type=int, default=10,
                      help="Bu çalıştırmada indirilecek maksimum kayıt (varsayılan 10)")
    opts = argp.parse_args()
    main(opts.limit)
