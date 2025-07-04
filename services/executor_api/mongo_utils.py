#!/usr/bin/env python3
# services/executor_api/mongo_utils.py

import os
import re
import logging
import time
from datetime import datetime
from pymongo import MongoClient
from typing import List, Dict, Any, Optional

# ───────────────────────────── ENV & GLOBALS ─────────────────────────────

# 1) MongoDB URI ve veritabanı adı .env’den okunuyor
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB  = os.getenv("MONGO_DB", "mikrosalesiq")

# 2) MongoClient oluşturup, doğru veritabanını seçiyoruz
client = MongoClient(MONGO_URI)
db     = client[MONGO_DB]

# 3) Koleksiyonlar
call_records_coll = db["call_records"]
audio_jobs_coll   = db["audio_jobs"]

# 4) Logger ve tarih formatı regex’i
log     = logging.getLogger("mongo_utils")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # YYYY-MM-DD formata uygun


def aggregate_status(calls: List[Dict[str, Any]]) -> str:
    """
    audio_jobs içindeki tüm çağrıların 'status' alanlarına bakarak
    bir müşteri seviyesindeki job_status döndürür:
      - Eğer hepsi "downloaded" ise → "downloaded"
      - Eğer hepsi "queued" ise → "queued"
      - Eğer bir kısmı "downloaded" ise → "partial"
      - Aksi durum (örneğin hepsi ya da bir kısmı "error" ise) → "error"
    """
    states = {c.get("status") for c in calls}
    if states == {"downloaded"}:
        return "downloaded"
    if states <= {"queued"}:
        return "queued"
    if "downloaded" in states:
        return "partial"
    return "error"


# ───────────────────────── CALL_RECORDS Fonksiyonları ─────────────────────────

def get_calls_from_call_records(
    agent_email: str,
    start_date: Optional[str] = None,  # "YYYY-MM-DD"
    end_date:   Optional[str] = None   # "YYYY-MM-DD"
) -> List[Dict[str, Any]]:
    """
    call_records koleksiyonundan, verilen agent_email ve opsiyonel tarih aralığına
    göre (start_date, end_date) çağrı kayıtlarını çeker ve liste halinde döner.

    return format:
      [
        {
          "call_id": str,
          "call_key": str,
          "customer_num": str,
          "agent_email": str,
          "call_date": "YYYY-MM-DD HH:MM:SS",
          "direction": "inbound" | "outbound"
        },
        ...
      ]
    """
    match = {"agent_email": agent_email}

    # Eğer start_date/end_date geçerliyse, string olarak "YYYY-MM-DD HH:MM:SS" formatında karşılaştırma yap
    date_filter = {}
    if start_date and DATE_RE.match(start_date):
        date_filter["$gte"] = f"{start_date} 00:00:00"
    if end_date and DATE_RE.match(end_date):
        date_filter["$lte"] = f"{end_date} 23:59:59"
    if date_filter:
        match["call_date"] = date_filter

    projection = {
        "_id": 0,
        "call_id": 1,
        "call_key": 1,
        "customer_num": 1,
        "agent_email": 1,
        "call_date": 1,
        "direction": 1
    }

    cursor = call_records_coll.find(match, projection)
    results = list(cursor)
    log.info(f"call_records’dan {agent_email} için {len(results)} kayıt bulundu (filtre: {match}).")
    return results


# ───────────────────────── AUDIO_JOBS Fonksiyonları ─────────────────────────

def get_audio_jobs_for_agent(agent_email: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    audio_jobs koleksiyonunda, içinde ilgili agent_email geçen tüm çağrıları bulur.
    Dönen yapıda:
      {
        "cleaned": [
            {"customer_num": str, "call_id": str, "call_date": str, "transcript": str},
            ...
        ],
        "waiting": [
            {"customer_num": str, "call_id": str, "status": str, "call_date": str},
            ...
        ]
      }
    """
    docs = list(audio_jobs_coll.find({"calls.agent_email": agent_email}))
    cleaned = []
    waiting = []

    for doc in docs:
        cust = doc.get("customer_num")
        for call in doc.get("calls", []):
            if call.get("agent_email") != agent_email:
                continue
            st = call.get("status")
            if st == "cleaned":
                cleaned.append({
                    "customer_num": cust,
                    "call_id": call.get("call_id"),
                    "call_date": call.get("call_date"),
                    "transcript": call.get("transcript", "")
                })
            else:
                waiting.append({
                    "customer_num": cust,
                    "call_id": call.get("call_id"),
                    "status": st,
                    "call_date": call.get("call_date")
                })

    log.info(f"Audio_jobs için {agent_email}: cleaned={len(cleaned)}, waiting={len(waiting)}.")
    return {"cleaned": cleaned, "waiting": waiting}


def add_new_calls_to_customer(
    customer_num: str,
    new_calls: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    audio_jobs koleksiyonunda, verilen customer_num altındaki belgeye,
    new_calls listesindeki her bir çağrı (call_id, call_key, agent_email, call_date, direction)
    eğer zaten 'calls' alt dizisinde yoksa ekler ve status="queued" atar.

    Dönüş:
      {
        "inserted": <kaç adet yeni ekleme yapıldı>,
        "skipped": <kaç adet zaten var olduğu için atlandı>
      }
    """
    doc = audio_jobs_coll.find_one({"customer_num": customer_num})
    if not doc:
        # Eğer bu müşteri için hiç belge yoksa, hata fırlatalım:
        msg = f"{customer_num} için audio_jobs kaydı bulunamadı!"
        log.error(msg)
        raise ValueError(msg)

    existing_ids = {c.get("call_id") for c in doc.get("calls", [])}
    to_insert = []
    skipped   = 0

    for call in new_calls:
        cid = call.get("call_id")
        if not cid:
            continue
        if cid in existing_ids:
            skipped += 1
            continue

        obj = {
            "call_id":   cid,
            "call_key":  call.get("call_key"),
            "agent_email": call.get("agent_email"),
            "call_date": call.get("call_date"),
            "direction": call.get("direction", ""),
            "status":    "queued",
            # ileride indirildiğinde eklenecek alanlar (varsa):
            # "file_path": "", "downloaded_at": "", "transcript": "", "transcribed_at": ""
        }
        to_insert.append(obj)

    if to_insert:
        audio_jobs_coll.update_one(
            {"customer_num": customer_num},
            {"$push": {"calls": {"$each": to_insert}}}
        )

    # job_status’ı yeniden hesaplayalım
    updated_doc = audio_jobs_coll.find_one(
        {"customer_num": customer_num},
        {"calls.status": 1}
    )
    if updated_doc:
        new_stat = aggregate_status(updated_doc["calls"])
        audio_jobs_coll.update_one(
            {"customer_num": customer_num},
            {"$set": {"job_status": new_stat}}
        )

    log.info(f"{customer_num} için new_calls ekleme: inserted={len(to_insert)}, skipped={skipped}.")
    return {"inserted": len(to_insert), "skipped": skipped}


def update_job_status(customer_num: str) -> str:
    """
    customer_num altındaki tüm çağrıların status’larına bakarak
    job_status’ı hesaplar ve MongoDB’de günceller. Yeni job_status’u döner.

    Örn:
      - Eğer hepsi "downloaded" ise → "downloaded"
      - Eğer hepsi "queued" ise → "queued"
      - Eğer bir kısmı "downloaded" ise → "partial"
      - Aksi halde → "error"
    """
    doc = audio_jobs_coll.find_one(
        {"customer_num": customer_num},
        {"calls.status": 1}
    )
    if not doc:
        raise ValueError(f"{customer_num} için audio_jobs belgesi yok.")
    new_s = aggregate_status(doc["calls"])
    audio_jobs_coll.update_one(
        {"customer_num": customer_num},
        {"$set": {"job_status": new_s}}
    )
    log.info(f"{customer_num} için job_status → {new_s}")
    return new_s
def save_mini_rag_summary(
    customer_num: str,
    summary_json: Dict[str, Any],
    merged_transcript: str,
    confidence: float,
    token_count: int,
    audio_features: Dict[str, Any]
):
    """
    Mini-RAG çıktısını audio_jobs koleksiyonuna kaydeder.
    """
    update_payload = {
        "mini_rag.summary": summary_json.get("summary"),
        "mini_rag.customer_profile": summary_json.get("customer_profile"),
        "mini_rag.sales_scores": summary_json.get("sales_scores"),
        "mini_rag.audio_analysis": summary_json.get("audio_analysis"),
        "mini_rag.recommendations": summary_json.get("recommendations"),
        "mini_rag.next_steps": summary_json.get("next_steps"),
        "mini_rag.conversion_probability": summary_json.get("conversion_probability"),
        "mini_rag.risk_score": summary_json.get("risk_score"),
        "mini_rag.merged_transcript": merged_transcript,
        "mini_rag.confidence": confidence,
        "mini_rag.token_count": token_count,
        "mini_rag.generated_at": time.time(),
        "mini_rag.audio_features_summary": audio_features
    }
        
    result = audio_jobs_coll.update_one(
        {"customer_num": customer_num},
        {"$set": update_payload}
    )

    if result.modified_count == 1:
        log.info(f"{customer_num} için Mini-RAG MongoDB güncellendi.")
    else:
        log.warning(f"{customer_num} için Mini-RAG güncellenemedi veya zaten aynıydı.")
