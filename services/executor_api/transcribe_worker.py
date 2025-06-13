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

# MongoDB bağlantısı
MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB   = os.getenv("MONGO_DB",  "mikrosalesiq")
AUDIO_COLL = "audio_jobs"

client_mongo = pymongo.MongoClient(MONGO_URI)
db           = client_mongo[MONGO_DB]
jobs_coll    = db[AUDIO_COLL]

# Redis bağlantısı ve kuyruk adları
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")
rds              = redis.from_url(REDIS_URL)
TRANSCRIBE_QUEUE = "transcribe_jobs"
CLEAN_QUEUE      = "clean_jobs"

# Dosya kökleri (env’den geliyorsa, yoksa default)
DOWNLOAD_ROOT = os.getenv("DOWNLOAD_ROOT", "recordings")
OUTPUT_ROOT   = os.getenv("OUTPUT_ROOT",   "output")

# ───────────────────────────── WHISPERX & DIARIZATION ─────────────────────────────

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
log.info("WhisperX modeli yükleniyor (device=%s)...", DEVICE)

if DEVICE == "cpu":
    whisper_model = whisperx.load_model(
        "large-v3",
        device=DEVICE,
        compute_type="float32"
    )
else:
    whisper_model = whisperx.load_model(
        "large-v3",
        device=DEVICE
    )

HF_TOKEN = os.getenv("HF_TOKEN", None)
log.info("Pyannote diarization pipeline yükleniyor (HF_TOKEN var mı? %s)...", bool(HF_TOKEN))
diarize_model = DiarPipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=HF_TOKEN
)

# ───────────────────────────── HELPERS ─────────────────────────────

def make_seekable_wav(input_path: str) -> str:
    temp_path = f"/tmp/seekable_{os.path.basename(input_path)}"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        temp_path
    ]
    subprocess.run(cmd, check=True)
    return temp_path


def align_segments_with_speakers(
    whisper_segs: List[Dict[str, Any]],
    diar: Annotation
) -> List[Dict[str, Any]]:
    tracks = list(diar.itertracks(yield_label=True))
    aligned = []
    for seg in whisper_segs:
        w_start, w_end = seg["start"], seg["end"]
        chosen_speaker = "Unknown"
        for turn, _, speaker in tracks:
            if turn.start <= w_end and turn.end >= w_start:
                chosen_speaker = speaker
                break
        seg["speaker"] = chosen_speaker
        aligned.append(seg)
    return aligned

def format_raw_output(
    segments: List[Dict[str, Any]],
    customer: str,
    agent: str
) -> str:
    lines: List[str] = []
    for seg in segments:
        speaker_label = agent if seg.get("speaker") == "SPEAKER_00" else customer
        text = seg.get("text", "").strip().replace("\n", " ")
        lines.append(f"{speaker_label}: {text}")
    return "\n".join(lines)

def update_job_status(customer_num: str) -> None:
    doc = jobs_coll.find_one(
        {"customer_num": customer_num},
        {"calls.status": 1}
    )
    if not doc:
        return

    statuses = [c.get("status") for c in doc.get("calls", [])]
    if all(s == "cleaned" for s in statuses):
        new_status = "completed"
    elif "error" in statuses:
        new_status = "error"
    elif "transcribed" in statuses or "downloaded" in statuses:
        new_status = "in_progress"
    else:
        new_status = "queued"

    jobs_coll.update_one(
        {"customer_num": customer_num},
        {"$set": {"job_status": new_status}}
    )

# ───────────────────────────── ANA DÖNGÜ ─────────────────────────────

def main(poll_interval: int = 5):
    log.info("transcribe_worker başladı – Kuyruk: '%s'", TRANSCRIBE_QUEUE)

    while True:
        job = rds.lpop(TRANSCRIBE_QUEUE)
        if not job:
            time.sleep(poll_interval)
            continue

        call_id = job.decode("utf-8")
        log.info(f"➜ Transkripsiyon: call_id={call_id}")

        # 1) MongoDB’den çağrı bilgisini çek
        doc = jobs_coll.find_one(
            {"calls.call_id": call_id},
            {"customer_num": 1, "calls.$": 1}
        )
        if not doc or "calls" not in doc or not doc["calls"]:
            log.error(f"⚠ audio_jobs içinde call_id={call_id} bulunamadı")
            continue

        customer_num = doc["customer_num"]
        call_obj     = doc["calls"][0]
        file_path    = call_obj.get("file_path")
        agent_email  = call_obj.get("agent_email", "Temsilci")

        # 2) file_path varsa mutlak yola dönüştür
        if not file_path:
            log.error(f"⚠ file_path alanı boş: call_id={call_id}")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "error",
                    "calls.$.error":  "file_path boş"
                }}
            )
            update_job_status(customer_num)
            continue

        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            log.error(f"⚠ Dosya bulunamadı (absolute): {abs_path}")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "error",
                    "calls.$.error":  "file not found"
                }}
            )
            update_job_status(customer_num)
            continue

        # 3) WhisperX ile diskten oku
        try:
            log.info(f"✅ Dosya yükleniyor (WhisperX.load_audio): {abs_path}")
            audio = whisperx.load_audio(abs_path)
            log.info(f"   → Yüklenen audio şekli: {audio.shape}, model sample rate’te")
        except Exception as e:
            log.error(f"❌ call_id={call_id} – WhisperX.load_audio hatası: {e}")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "error",
                    "calls.$.error":  f"Audio yükleme hatası: {e}"
                }}
            )
            update_job_status(customer_num)
            continue

        # 4) WhisperX transcribe
        try:
            log.info("🎧 WhisperX transkripsiyon başlıyor…")
            result = whisper_model.transcribe(audio)

            # 5) Pyannote diarization (seekable hatası önlemek için dict kullan)
            log.info("👥 Pyannote diarization başlıyor…")
            seekable_path = make_seekable_wav(abs_path)
            diar_input = { "uri": call_id, "audio": seekable_path }
            diar = diarize_model(diar_input)

            # 6) Segment’leri hizala
            aligned = align_segments_with_speakers(result["segments"], diar)
            transcript_text = format_raw_output(aligned, customer_num, agent_email)

            # 7) Çıktıyı diske yaz
            out_dir = Path(OUTPUT_ROOT) / customer_num
            out_dir.mkdir(parents=True, exist_ok=True)
            raw_path = out_dir / f"{call_id}.txt"
            raw_path.write_text(transcript_text, encoding="utf-8")
            log.info(f"✅ Transkripsiyon tamamlandı: {raw_path}")

            # 8) MongoDB kaydını güncelle
            res= jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status":       "transcribed",
                    "calls.$.transcript":   transcript_text,
                    "calls.$.transcribed_at": datetime.utcnow()
                }}
                )
            if res.matched_count == 0:
                log.error(f"⚠ call_id={call_id} için MongoDB güncellemesi başarısız")
            elif res.modified_count == 0:
                log.warning(f"⚠ call_id={call_id} için MongoDB kaydı zaten güncellenmiş")
            else:
                log.info(f"✅ MongoDB kaydı güncellendi: call_id={call_id}")

        except Exception as e:
            log.error(f"❌ call_id={call_id} transkripsiyon hatası: {e}")
            jobs_coll.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "error",
                    "calls.$.error":  str(e)
                }}
            )
            update_job_status(customer_num)
            continue

        # 9) Clean aşaması için kuyruğa ekle
        rds.rpush(CLEAN_QUEUE, call_id)
        log.info(f"→ Clean kuyruğuna eklendi: {call_id}")

        # 10) Müşteri seviyesinde job_status güncelle
        update_job_status(customer_num)
        os.remove(seekable_path)

if __name__ == "__main__":
    main(poll_interval=5)
