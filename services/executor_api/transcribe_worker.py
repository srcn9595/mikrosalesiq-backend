#!/usr/bin/env python3
# services/executor_api/transcribe_worker.py

import os
import time
import logging
import redis
import pymongo
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import subprocess
import importlib.util                                     # ➊  hf_transfer kontrolü

import torch
import whisperx
from pyannote.audio import Pipeline as DiarPipeline
from pyannote.core import Annotation

# ───────────────────────────── LOGGING ─────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("transcribe_worker")

# ───────────────────────────── ENV & GLOBALS ─────────────────────────────
MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB   = os.getenv("MONGO_DB",  "mikrosalesiq")
AUDIO_COLL = "audio_jobs"

client_mongo = pymongo.MongoClient(MONGO_URI)
db           = client_mongo[MONGO_DB]
jobs_coll    = db[AUDIO_COLL]

REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")
rds              = redis.from_url(REDIS_URL)
TRANSCRIBE_QUEUE = "transcribe_jobs"
CLEAN_QUEUE      = "clean_jobs"
DOWNLOAD_QUEUE   = "download_jobs"

DOWNLOAD_ROOT = os.getenv("DOWNLOAD_ROOT", "recordings")
OUTPUT_ROOT   = os.getenv("OUTPUT_ROOT",   "output")

# ───────────────────────────── WHISPERX & DIARIZATION ─────────────────────────────
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
log.info("WhisperX modeli yükleniyor (device=%s)…", DEVICE)

MODEL_ID = os.getenv("WHISPER_MODEL", "Systran/faster-whisper-large-v3")

# ➋  hf_transfer kütüphanesi yoksa hızlı indirmeyi kapat
if "HF_HUB_ENABLE_HF_TRANSFER" in os.environ and not importlib.util.find_spec("hf_transfer"):
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

# ➌  Modeli doğru argümanlarla yükle
LOCAL_ONLY = os.getenv("HF_LOCAL_ONLY", "false").lower() == "true"

if DEVICE == "cpu":
    whisper_model = whisperx.load_model(
        MODEL_ID,
        device=DEVICE,
        compute_type="float32",
        local_files_only=LOCAL_ONLY
    )
else:
    whisper_model = whisperx.load_model(
        MODEL_ID,
        device=DEVICE,
        local_files_only=LOCAL_ONLY
    )

HF_TOKEN = os.getenv("HF_TOKEN")
log.info("Pyannote diarization pipeline yükleniyor (HF_TOKEN var mı? %s)…", bool(HF_TOKEN))
diarize_model = DiarPipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=HF_TOKEN
)

# ───────────────────────────── HELPERS ─────────────────────────────
def make_seekable_wav(input_path: str) -> str:
    tmp = f"/tmp/seekable_{os.path.basename(input_path)}"
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return tmp

def align_segments_with_speakers(whisper_segs: List[Dict[str, Any]], diar: Annotation):
    tracks = list(diar.itertracks(yield_label=True))
    for seg in whisper_segs:
        w_start, w_end = seg["start"], seg["end"]
        seg["speaker"] = next(
            (spk for turn, _, spk in tracks if turn.start <= w_end and turn.end >= w_start),
            "Unknown",
        )
    return whisper_segs

def format_raw_output(segments, customer, agent):
    lines = []
    for s in segments:
        who = agent if s.get("speaker") == "SPEAKER_00" else customer
        lines.append(f"{who}: {s.get('text','').strip().replace(chr(10), ' ')}")
    return "\n".join(lines)

def update_job_status(customer_num: str):
    doc = jobs_coll.find_one({"customer_num": customer_num}, {"calls.status": 1})
    if not doc:
        return
    st = [c.get("status") for c in doc.get("calls", [])]
    new = (
        "completed"   if all(s == "cleaned"     for s in st) else
        "error"       if "error"        in st   else
        "in_progress" if {"transcribed","downloaded"} & set(st) else
        "queued"
    )
    jobs_coll.update_one({"customer_num": customer_num}, {"$set": {"job_status": new}})

# ───────────────────────────── ANA DÖNGÜ ─────────────────────────────
def main(poll_interval: int = 5):
    log.info("transcribe_worker başladı – Kuyruk: '%s'", TRANSCRIBE_QUEUE)
    while True:
        job = rds.lpop(TRANSCRIBE_QUEUE)
        if not job:
            time.sleep(poll_interval)
            continue

        call_id = job.decode()
        log.info("➜ Transkripsiyon: %s", call_id)

        doc = jobs_coll.find_one({"calls.call_id": call_id}, {"customer_num": 1, "calls.$": 1})
        if not doc or not doc.get("calls"):
            log.error("⚠ audio_jobs içinde call_id=%s bulunamadı", call_id)
            continue

        customer_num = doc["customer_num"]
        call_obj     = doc["calls"][0]
        file_path    = call_obj.get("file_path")
        agent_email  = call_obj.get("agent_email", "Temsilci")

        if not file_path or not os.path.exists(file_path):
            log.warning("📥 WAV yok – yeniden download kuyruğuna alınıyor")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "queued", "calls.$.file_path": None, "calls.$.error": None}}
            )
            rds.rpush(DOWNLOAD_QUEUE, call_id)
            update_job_status(customer_num)
            continue

        try:
            audio = whisperx.load_audio(file_path)
        except Exception as e:
            log.error("❌ Audio yüklenemedi: %s", e)
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "error", "calls.$.error": f"Audio yükleme: {e}"}}
            )
            update_job_status(customer_num)
            continue

        try:
            result = whisper_model.transcribe(audio)
            seekable = make_seekable_wav(file_path)
            diar     = diarize_model({"uri": call_id, "audio": seekable})
            aligned  = align_segments_with_speakers(result["segments"], diar)
            text     = format_raw_output(aligned, customer_num, agent_email)

            out_dir = Path(OUTPUT_ROOT) / customer_num
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{call_id}.txt").write_text(text, encoding="utf-8")

            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "transcribed",
                    "calls.$.transcript": text,
                    "calls.$.transcribed_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            log.error("❌ Transkripsiyon hatası: %s", e)
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {"calls.$.status": "error", "calls.$.error": str(e)}}
            )
            update_job_status(customer_num)
            continue
        finally:
            if 'seekable' in locals() and os.path.exists(seekable):
                os.remove(seekable)

        rds.rpush(CLEAN_QUEUE, call_id)
        log.info("→ Clean kuyruğuna eklendi: %s", call_id)
        update_job_status(customer_num)

if __name__ == "__main__":
    main(poll_interval=5)
