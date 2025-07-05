#!/usr/bin/env python3
"""
services/executor_api/transcribe_worker.py

GPU-hızlı, KVKK-uyumlu transkripsiyon & diarization
--------------------------------------------------
• WhisperX fp16 + toplu iş (CUDA 12.4)
• Pyannote diarization doğrudan GPU’da
• Redis BLPOP → bloklu (busy-wait yok)
• OOM durumunda batch-size’i yarıya düşürüp yeniden dener
• 3 denemeye kadar otomatik retry + back-off
"""
from __future__ import annotations

import importlib.util, logging, os, subprocess, time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import whisperx, torch, pymongo, redis
from pyannote.audio import Pipeline as DiarPipeline
from pyannote.core import Annotation
from kvkk_guard import mask_sensitive_info
from audio_features_worker import process_call          # senkron
from queue_utils import (
    dequeue_download, dequeue_call_insights, dequeue_mini_rag,
    mark_clean_enqueued, mark_failed
)
from shared_lib.notification_utils import (
    get_notification_id_for_call,
    update_job_in_notification,
    finalize_notification_if_ready
)

# ─────────────────────── Ayarlar ───────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB",  "mikrosalesiq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

TRANS_Q, DL_Q = "transcribe_jobs", "download_jobs"
OUTPUT_ROOT   = os.getenv("OUTPUT_ROOT", "output")

MAX_RETRIES   = int(os.getenv("MAX_RETRIES",   "3"))
RETRY_DELAY_S = int(os.getenv("RETRY_DELAY_S", "5"))

MODEL_ID   = os.getenv("WHISPER_MODEL", "Systran/faster-whisper-large-v3")
BATCH_SZ   = int(os.getenv("WHISPER_BATCH", "16"))
COMPUTE_T  = os.getenv("WHISPER_PREC",  "float16")
LOCAL_ONLY = os.getenv("HF_LOCAL_ONLY", "false").lower() == "true"
HF_TOKEN   = os.getenv("HF_TOKEN")

DEVICE_STR = "cuda" if torch.cuda.is_available() else "cpu"
DEVICE     = torch.device(DEVICE_STR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("transcribe_worker")

# ─────────────────────── Mongo / Redis ───────────────────────
client = pymongo.MongoClient(MONGO_URI)
db     = client[MONGO_DB]           # <-- database (notifications)
audio  = db["audio_jobs"]           # <-- collection (calls)

rds = redis.from_url(REDIS_URL)

# ─────────────────────── Modeller ───────────────────────
log.info("WhisperX yükleniyor: %s (batch=%d, %s, device=%s)",
         MODEL_ID, BATCH_SZ, COMPUTE_T, DEVICE_STR)

if "HF_HUB_ENABLE_HF_TRANSFER" in os.environ and not importlib.util.find_spec("hf_transfer"):
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

whisper_model = whisperx.load_model(
    MODEL_ID,
    device=DEVICE_STR,
    compute_type=COMPUTE_T,
    local_files_only=LOCAL_ONLY,
)

log.info("Pyannote diarization pipelini GPU'ya geçiriliyor…")
diarize_model = (
    DiarPipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=HF_TOKEN,
    ).to(DEVICE)
)

TMP_DIR = "/tmp"

# ─────────────────────── Yardımcılar ───────────────────────
def make_seekable(src: str) -> str:
    dst = f"{TMP_DIR}/seek_{Path(src).stem}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", dst],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )
    return dst

def align_segments(seg: List[Dict[str, Any]], diar: Annotation) -> List[Dict[str, Any]]:
    tracks = list(diar.itertracks(yield_label=True))
    for s in seg:
        if any(turn.start <= s["end"] and turn.end >= s["start"] for turn, _, _ in tracks):
            s["speaker"] = next(spk for turn, _, spk in tracks
                                if turn.start <= s["end"] and turn.end >= s["start"])
        else:
            s["speaker"] = "Unknown"
    return seg

def segments_to_text(seg, customer: str, agent: str) -> str:
    return "\n".join(
        f"{agent if s.get('speaker') == 'SPEAKER_00' else customer}: "
        f"{s.get('text', '').strip().replace(chr(10), ' ')}"
        for s in seg
    )

def update_parent_status(customer_num: str) -> None:
    doc = audio.find_one({"customer_num": customer_num}, {"calls.status": 1})
    if not doc:
        return
    st = [c.get("status") for c in doc.get("calls", [])]
    status = ("completed"   if all(x == "cleaned" for x in st) else
              "error"       if "error" in st else
              "in_progress" if {"downloaded", "transcribed"} & set(st) else
              "queued")
    audio.update_one({"customer_num": customer_num},
                     {"$set": {"job_status": status}})

# ─────────────────────── Ana döngü ───────────────────────
def main() -> None:
    log.info("Transcribe worker hazır (queue=%s)", TRANS_Q)

    while True:
        _job = rds.blpop(TRANS_Q)           # bloklu
        call_id = _job[1].decode()

        rec = audio.find_one({"calls.call_id": call_id},
                             {"customer_num": 1, "calls.$": 1})
        if not rec or not rec.get("calls"):
            log.error("call_id=%s veritabanında yok!", call_id)
            continue

        customer = rec["customer_num"]
        call     = rec["calls"][0]
        path     = call.get("file_path")
        agent    = call.get("agent_email", "Temsilci")
        retries  = call.get("retry_count", 0)

        # ---------- Dosya yoksa geri download kuyruğuna ----------
        if not path or not Path(path).exists():
            log.warning("WAV bulunamadı → download kuyruğu (id=%s)", call_id)
            audio.update_one({"calls.call_id": call_id},
                             {"$set": {"calls.$.status": "queued",
                                       "calls.$.file_path": None}})
            rds.rpush(DL_Q, call_id)
            update_parent_status(customer)
            continue

        # ---------- Transkripsiyon ----------
        success = False
        try:
            audio_arr = whisperx.load_audio(path)
            bs = BATCH_SZ
            while True:
                try:
                    result = whisper_model.transcribe(audio_arr, batch_size=bs)
                    break
                except RuntimeError as e:
                    if "out of memory" in str(e).lower() and bs > 1:
                        bs = max(1, bs // 2)
                        log.warning("CUDA OOM — batch=%d → %d", bs*2, bs)
                        torch.cuda.empty_cache()
                        time.sleep(1)
                        continue
                    raise

            seek  = make_seekable(path)
            diar  = diarize_model({"uri": call_id, "audio": seek})
            aligned = align_segments(result["segments"], diar)

            raw_txt   = segments_to_text(aligned, customer, agent)
            clean_txt = mask_sensitive_info(raw_txt)

            out_dir = Path(OUTPUT_ROOT) / customer
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{call_id}.txt").write_text(clean_txt, encoding="utf-8")

            if process_call(call_id):
                log.info("🔊 Audio features senkron eklendi.")
            else:
                log.warning("⚠️ Audio features çıkarılamadı.")

            audio.update_one(
                {"calls.call_id": call_id},
                {"$set": {
                    "calls.$.status": "transcribed",
                    "calls.$.raw_transcript": raw_txt,
                    "calls.$.transcript":   clean_txt,
                    "calls.$.transcribed_at": datetime.utcnow(),
                    "calls.$.retry_count":   retries,
                    "calls.$.segments": aligned
                }}
            )
            success = True

        # ---------- Hata / Retry ----------
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and retries < MAX_RETRIES:
                log.warning("OOM — retry (%d/%d)", retries+1, MAX_RETRIES)
                time.sleep(RETRY_DELAY_S)
                audio.update_one({"calls.call_id": call_id},
                                 {"$set": {"calls.$.retry_count": retries + 1}})
                rds.rpush(TRANS_Q, call_id)
            else:
                log.exception("Transkripsiyon hatası:")
                audio.update_one({"calls.call_id": call_id},
                                 {"$set": {"calls.$.status": "error",
                                           "calls.$.error": str(e),
                                           "calls.$.retry_count": retries}})

        except Exception as e:
            log.exception("Genel hata:")
            audio.update_one({"calls.call_id": call_id},
                             {"$set": {"calls.$.status": "error",
                                       "calls.$.error": str(e),
                                       "calls.$.retry_count": retries}})

        finally:
            if 'seek' in locals() and Path(seek).exists():
                Path(seek).unlink(missing_ok=True)
            torch.cuda.empty_cache()

            # ---------- Notification update ----------
            try:
                notification_id = get_notification_id_for_call(db, call_id)
                log.info("Notification ID: %s", notification_id)
                if notification_id:
                    update_job_in_notification(
                        mongo=db,                                           
                        notification_id=notification_id,
                        customer_num=customer,
                        call_id=call_id,
                        job_status="done" if success else "failed",
                        result={"transcribed": success},
                        error=None if success else "Transcription failed"
                    )
                    #finalize_notification_if_ready(db, notification_id)
            except Exception as e:
                log.warning("Notification update failed: %s", e)

            # ---------- Kuyruk & durum güncellemeleri ----------
            if success or retries >= MAX_RETRIES:
                dequeue_download(call_id)
                dequeue_call_insights(call_id)
                dequeue_mini_rag(customer)

            if success:
                mark_clean_enqueued(call_id)
            elif retries >= MAX_RETRIES:
                mark_failed(call_id)

            update_parent_status(customer)

if __name__ == "__main__":
    main()
