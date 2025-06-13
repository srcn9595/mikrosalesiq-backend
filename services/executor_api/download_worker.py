#!/usr/bin/env python3
# services/executor_api/download_worker.py

import os
import time
import logging
import requests
import redis
import pymongo
from datetime import datetime, timedelta
from typing import Optional

# ───────────────────────────── LOGGING ─────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("download_worker")

# ───────────────────────────── ENV & GLOBALS ─────────────────────────────

# 1) MongoDB / Redis bağlantı bilgileri .env’den alınıyor
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB", "mikrosalesiq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
AUDIO_COLL = "audio_jobs"

# MongoClient oluştur ve doğru veritabanını seç
client_mongo = pymongo.MongoClient(MONGO_URI)
db = client_mongo[MONGO_DB]
jobs_coll = db[AUDIO_COLL]

# Redis bağlantısı
rds = redis.from_url(REDIS_URL)
DOWNLOAD_QUEUE = "download_jobs"
TRANSCRIBE_QUEUE = "transcribe_jobs"

# ───────────────────────────── ALoTech AYARLARI ─────────────────────────────
# Bunları .env içerisinde tanımladığımız değişkenlerden alıyoruz:
ALOTECH_CONFIG = {
    "client_id":      os.getenv("ALO_CLIENT_ID", ""),
    "client_secret":  os.getenv("ALO_CLIENT_SECRET", ""),
    "token_url":      os.getenv("ALO_TOKEN_URL", "https://parasut.alo-tech.com/application/access_token/"),
    "tenant":         os.getenv("ALO_TENANT", "parasut.alo-tech.com"),
    "rec_api":        os.getenv("ALO_REC_API_TEMPLATE", "https://parasut.alo-tech.com/v3/calls/{key}/recordings"),
}

# İndirme klasörü
DOWNLOAD_ROOT = os.getenv("DOWNLOAD_ROOT", "recordings")
# Zaman damgası için format
TIME_FMT = "%Y-%m-%d_%H-%M-%S"

# token cache
_token_val: Optional[str] = None
_token_expires: datetime = datetime.min


def get_access_token(force: bool = False) -> str:
    """
    ALoTech API için OAuth token alır. Eğer token süresi geçmişse (veya force=True ise),
    yenisini alır; aksi takdirde cache’teki değeri döner.
    """
    global _token_val, _token_expires

    if force or datetime.utcnow() >= _token_expires:
        # Yeni token isteği
        payload = {
            "client_id": ALOTECH_CONFIG["client_id"],
            "client_secret": ALOTECH_CONFIG["client_secret"],
        }
        r = requests.post(ALOTECH_CONFIG["token_url"], json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        _token_val = data["access_token"]

        # Bitiş zamanını hesapla (örn. 3600 saniye sonra)
        ttl = data.get("expires_in") or data.get("duration") or 3600
        _token_expires = datetime.utcnow() + timedelta(seconds=ttl - 30)
        log.info("🔑 Yeni ALoTech token alındı, geçerlilik: %s", _token_expires)

    return _token_val


def fetch_recording(call_key: str, headers: dict, retry: bool = True) -> bytes:
    """
    Verilen call_key’e göre ALoTech’ten ses verisini indirir.
    - Eğer ilk seferde 401 hatası gelirse token’ı yeniler ve tekrar dener.
    - Eğer 429 hatası gelirse, 'Retry-After' başlığına bakar ve bekleyip yeniden dener.
    - Eğer direkt 'audio' veya 'octet-stream' içerik tipi gelirse, ham byte’ları döner.
    - Aksi takdirde, JSON içinde "url" vs. varsa o link’ten dosyayı indirir.
    """
    url = ALOTECH_CONFIG["rec_api"].format(key=call_key)
    r = requests.get(url, headers=headers, params={"copy_recording": "false"}, timeout=60)

    # 1) 401 Unauthorized → token’ı yenile ve tekrar dene
    if r.status_code == 401 and retry:
        headers["Authorization"] = f"Bearer {get_access_token(force=True)}"
        return fetch_recording(call_key, headers, retry=False)

    # 2) 429 Rate limit → 'Retry-After' bekle ve tekrar dene
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "5"))
        log.warning("429 RateLimit – %s saniye bekleniyor...", wait)
        time.sleep(wait)
        return fetch_recording(call_key, headers, retry)

    r.raise_for_status()
    ctype = r.headers.get("content-type", "")

    # 3) Eğer doğrudan ses/veri gelmişse
    if "audio" in ctype or "octet-stream" in ctype:
        return r.content

    # 4) Aksi takdirde JSON formattır, "url" ya da "recording_url" alanından link al
    try:
        data = r.json()
        link = data.get("url") or data.get("recording_url")
        if not link:
            raise RuntimeError("ALoTech yanıtında 'url' bulunamadı.")
        a = requests.get(link, timeout=60)
        a.raise_for_status()
        return a.content
    except Exception as e:
        raise RuntimeError(f"Beklenmeyen ALoTech yanıtı: {r.text[:200]}... ({e})")


def save_audio_file(
    customer_num: str,
    call_date_str: str,
    call_id: str,
    audio_bytes: bytes
) -> str:
    """
    İndirilen byte verisini, klasör yapısı içinde (DOWNLOAD_ROOT/<customer_num>/) WAV dosyası olarak kaydeder.
    Return: Dosyanın tam yolu.
    """
    ts = datetime.strptime(call_date_str, "%Y-%m-%d %H:%M:%S")
    fname = f"{ts.strftime(TIME_FMT)}_{call_id}.wav"
    out_dir = os.path.join(DOWNLOAD_ROOT, customer_num)
    os.makedirs(out_dir, exist_ok=True)
    fullpath = os.path.join(out_dir, fname)

    with open(fullpath, "wb") as f:
        f.write(audio_bytes)

    return fullpath


def update_job_status(customer_num: str) -> None:
    """
    audio_jobs koleksiyonunda, ilgili müşteri için tüm çağrıların 'status' alanına bakar.
    - Eğer hepsi "downloaded" ise → new_status="downloaded_all"
    - Eğer en az bir tanesi "error" ise → new_status="error"
    - Aksi takdirde → new_status="in_progress"
    Ardından MongoDB'deki job_status alanını günceller.
    """
    doc = jobs_coll.find_one(
        {"customer_num": customer_num},
        {"calls.status": 1}
    )
    if not doc:
        return

    statuses = [c.get("status") for c in doc.get("calls", [])]
    if all(s == "downloaded" for s in statuses):
        new_status = "downloaded_all"
    elif any(s == "error" for s in statuses):
        new_status = "error"
    else:
        new_status = "in_progress"

    jobs_coll.update_one(
        {"customer_num": customer_num},
        {"$set": {"job_status": new_status}}
    )


def main(poll_interval: int = 5):
    """
    Sürekli olarak Redis 'download_jobs' kuyruğunu dinler.
    Her bir call_id aldığında:
      1) MongoDB'den çağrı detaylarını getir (call_key, call_date, vs.)
      2) ALoTech API'den sesi indir
      3) Kaydedilen dosya yolunu MongoDB'ye yaz, status="downloaded"
      4) Redis 'transcribe_jobs' kuyruğuna call_id ekle
      5) job_status güncelle
    """
    log.info("download_worker başladı – Kuyruk: '%s'", DOWNLOAD_QUEUE)

    # Başlangıçta token alıyoruz
    headers = {
        "Tenant": ALOTECH_CONFIG["tenant"],
        "Authorization": f"Bearer {get_access_token()}"
    }

    while True:
        job = rds.lpop(DOWNLOAD_QUEUE)
        if not job:
            time.sleep(poll_interval)
            continue

        call_id = job.decode("utf-8")
        log.info(f"➜ İndiriliyor: call_id={call_id}")

        # 1) MongoDB’den ilgili çağrıyı çek
        doc = jobs_coll.find_one(
            {"calls.call_id": call_id},
            {"customer_num": 1, "calls.$": 1}
        )
        if not doc or "calls" not in doc or not doc["calls"]:
            log.error(f"⚠ audio_jobs içinde call_id={call_id} bulunamadı")
            continue

        customer_num = doc["customer_num"]
        call_obj     = doc["calls"][0]
        call_key     = call_obj.get("call_key")
        call_date    = call_obj.get("call_date")

        # 2) ALoTech’ten ses dosyasını indir
        try:
            audio_bytes = fetch_recording(call_key, headers)
            saved_path  = save_audio_file(customer_num, call_date, call_id, audio_bytes)

            # MongoDB: çağrı status'unu "downloaded" ve file_path’i güncelle
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "downloaded",
                    "calls.$.file_path": saved_path,
                    "calls.$.downloaded_at": datetime.utcnow()
                }}
            )
            log.info(f"✅ İndirildi: {saved_path}")
        except Exception as e:
            log.error(f"❌ call_id={call_id} indirme hatası: {e}")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "error",
                    "calls.$.error": str(e)
                }}
            )
            update_job_status(customer_num)
            continue

        # 3) Redis'e 'transcribe_jobs' kuyruğuna ekle
        rds.rpush(TRANSCRIBE_QUEUE, call_id)
        log.info(f"→ Transcribe kuyruğuna eklendi: {call_id}")

        # 4) job_status güncellemesi
        update_job_status(customer_num)


if __name__ == "__main__":
    main(poll_interval=5)
