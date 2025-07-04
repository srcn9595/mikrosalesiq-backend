import os
import logging
import pymongo
import subprocess
from pathlib import Path
from time import sleep
from queue_utils import _AUDIO_FEATURES_JOBS_KEY, rds
from audio_utils import extract_audio_features

# Logger
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("audio_features_worker")

# Ortam değişkenleri
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")  # Docker ortamı için hostname 'mongo'
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
BASE_DIR = os.getenv("BASE_DIR", "/app")  # Docker image icinde ana dizin
TMP_DIR  = os.getenv("TMP_DIR", "/tmp")
mongo    = pymongo.MongoClient(MONGO_URI)[MONGO_DB]

def make_seekable(src: str) -> str:
    dst = f"{TMP_DIR}/seek_{Path(src).stem}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", dst],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )
    return dst

def process_call(call_id: str) -> bool:
    log.info(f"🎿 İşleniyor: call_id={call_id}")
    collection = mongo["audio_jobs"]
    call = collection.find_one(
        {"calls.call_id": call_id},
        {"customer_num": 1, "calls.$": 1}
    )
    if not call or "calls" not in call or not call["calls"]:
        log.warning(f"❌ Call bulunamadı: {call_id}")
        return False

    call_data = call["calls"][0]
    audio_path = call_data.get("file_path")
    audio_path = os.path.join(BASE_DIR, audio_path)

    if not os.path.exists(audio_path):
        log.warning(f"❌ Ses dosyası eksik: {audio_path}")
        return False

    try:
        audio_path = make_seekable(audio_path)
    except subprocess.CalledProcessError as e:
        log.error(f"❌ ffmpeg ile dönüştürme hatası: {e}")
        return False

    features = extract_audio_features(audio_path, call_id, collection)

    if not features:
        log.warning(f"❌ Özellik çıkartılamadı: {call_id}")
        return False

    mongo.audio_jobs.update_one(
        {"calls.call_id": call_id},
        {"$set": {"calls.$.audio_features": features}}
    )

    log.info(f"✅ audio_features eklendi: {call_id}")
    return True

def worker_loop():
    log.info("🔊 Kuyruktan iş dinleniyor...")
    while True:
        job = rds.blpop(_AUDIO_FEATURES_JOBS_KEY)
        if not job:
            sleep(1)
            continue

        call_id = job[1].decode()
        process_call(call_id)

if __name__ == "__main__":
    TEST_CALL_ID = os.getenv("TEST_CALL_ID")  # Docker ortamından id alabilir
    if TEST_CALL_ID:
        log.info(f"🧪 Tek seferlik test başlatılıyor: {TEST_CALL_ID}")
        process_call(TEST_CALL_ID)
    else:
        worker_loop()
