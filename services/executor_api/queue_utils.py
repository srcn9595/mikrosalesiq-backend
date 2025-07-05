import os
import redis
from typing import Any,List, Dict,Optional
import json
import logging
log = logging.getLogger(__name__)
from shared_lib.notification_utils import create_notification_job
from datetime import datetime
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
rds = redis.from_url(REDIS_URL)

_DOWNLOAD_JOBS_KEY              = "download_jobs"
_DOWNLOAD_ENQUEUED_SET          = "download_enqueued_set"
_CALL_INSIGHTS_JOBS_KEY         = "call_insights_jobs"
_CALL_INSIGHTS_ENQUEUED_SET     = "call_insights_enqueued_set"
_MINI_RAG_JOBS_KEY              = "mini_rag_jobs"
_MINI_RAG_ENQUEUED_SET          = "mini_rag_enqueued_set"
_AUDIO_FEATURES_JOBS_KEY        = "audio_features_jobs"
_AUDIO_FEATURES_ENQUEUED_SET    = "audio_features_enqueued_set"
_CLEAN_JOBS_KEY                 = "clean_jobs"
_CLEAN_ENQUEUED_SET             = "clean_enqueued_set"
_FAILED_JOBS_KEY                = "failed_jobs"



# ────────────────────── ortak yardımcılar ──────────────────────
def _queue_position(key: str, item: str) -> int | None:
    """
    Redis listesinde ITEM'in kaçıncı sırada olduğunu döner.
    Yoksa None.
    """
    raw = rds.lrange(key, 0, -1)
    try:
        return raw.index(item.encode()) + 1
    except ValueError:
        return None

def _customer_from_call_id(mongo, call_id: str) -> str:
    """
    audio_jobs içinden call_id'ye karşılık gelen customer_num'u bulur.
    """
    doc = mongo["audio_jobs"].find_one({"calls.call_id": call_id}, {"customer_num": 1})
    return doc.get("customer_num", "") if doc else None

# ─────────────── dequeue helpers ───────────────
def dequeue_download(call_id: str) -> None:
    rds.srem(_DOWNLOAD_ENQUEUED_SET, call_id)

def dequeue_call_insights(call_id: str) -> None:
    rds.srem(_CALL_INSIGHTS_ENQUEUED_SET, call_id)

def dequeue_mini_rag(customer_num: str) -> None:
    rds.srem(_MINI_RAG_ENQUEUED_SET, customer_num)

# ────────────────────── FAILED KUYRUĞU ──────────────────────


def mark_failed(call_id: str) -> None:
    rds.rpush(_FAILED_JOBS_KEY, call_id)

def get_failed_jobs(limit: int = 100) -> List[str]:
    return [x.decode() for x in rds.lrange(_FAILED_JOBS_KEY, 0, limit - 1)]

def clear_failed_jobs() -> None:
    rds.delete(_FAILED_JOBS_KEY)

def failed_count() -> int:
    return rds.llen(_FAILED_JOBS_KEY)

# ────────────────────── CLEANED_KUYRUĞU ──────────────────────

def is_clean_enqueued(call_id: str) -> bool:
    return rds.sismember(_CLEAN_ENQUEUED_SET, call_id)

def mark_clean_enqueued(call_id: str) -> None:
    rds.sadd(_CLEAN_ENQUEUED_SET, call_id)
    rds.rpush(_CLEAN_JOBS_KEY, call_id)

def dequeue_clean(call_id: str) -> None:
    rds.srem(_CLEAN_ENQUEUED_SET, call_id)


# ────────────────────── DOWNLOAD KUYRUĞU ──────────────────────
def is_download_enqueued(call_id: str) -> bool:
    return rds.sismember(_DOWNLOAD_ENQUEUED_SET, call_id)


def mark_download_enqueued(call_id: str) -> None:
    rds.sadd(_DOWNLOAD_ENQUEUED_SET, call_id)
    rds.rpush(_DOWNLOAD_JOBS_KEY, call_id)


def enqueue_downloads(
    call_ids: List[str],
    *,
    notification_id: str | None = None,
    mongo=None
) -> Dict[str, Any]:
    new_items, already_items, positions = [], [], {}

    for cid in call_ids:
        if is_download_enqueued(cid):
            already_items.append(cid)
        else:
            mark_download_enqueued(cid)
            new_items.append(cid)
        positions[cid] = _queue_position(_DOWNLOAD_JOBS_KEY, cid)

    if notification_id and mongo is not None and call_ids:
        from bson import ObjectId
        customer_num = _customer_from_call_id(mongo, call_ids[0])
        notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
        if notif:
            jobs = notif.get("jobs", [])
            for job in jobs:
                if job.get("type") == "download_audio" and job.get("customer_num") == customer_num:
                    # SADECE yeni call_id'leri ekle
                    existing_call_ids = set(job.get("call_ids", []))
                    new_call_ids = [cid for cid in call_ids if cid not in existing_call_ids]
                    if new_call_ids:
                        mongo.notifications.update_one(
                            {
                                "_id": ObjectId(notification_id),
                                "jobs.customer_num": customer_num,
                                "jobs.type": "download_audio",
                            },
                            {
                                "$addToSet": {"jobs.$.call_ids": {"$each": new_call_ids}},
                                "$set": {"jobs.$.updated_at": datetime.utcnow()},
                            },
                        )
                    break
            else:
                # Böyle job yoksa sadece o zaman ekle
                create_notification_job(
                    mongo=mongo,
                    job_type="download_audio",
                    notification_id=notification_id,
                    customer_num=customer_num,
                    call_ids=call_ids,
                    status="pending"
                )
        # notif yoksa hiçbir şey yapma

    all_queued = [x.decode() for x in rds.lrange(_DOWNLOAD_JOBS_KEY, 0, -1)]
    return {
        "newly_enqueued":   len(new_items),
        "already_enqueued": len(already_items),
        "new_items":        new_items,
        "already_items":    already_items,
        "positions":        positions,
        "all_queued":       all_queued,
    }



# ────────────────────── MINI-RAG KUYRUĞU ──────────────────────
def is_mini_rag_enqueued(customer_num: str) -> bool:
    return rds.sismember(_MINI_RAG_ENQUEUED_SET, customer_num)


def enqueue_mini_rag(
    customer_num: str,
    notification_id: Optional[str] = None,
    mongo=None,
) -> Dict[str, Any]:
    log.info(f"enqueue_mini_rag: customer_num={customer_num}, notification_id={notification_id}")

    # 1) Zaten varsa sadece pozisyonunu döner
    if is_mini_rag_enqueued(customer_num):
        all_items = [json.loads(x.decode()) for x in rds.lrange(_MINI_RAG_JOBS_KEY, 0, -1)]
        position = next((i + 1 for i, ctx in enumerate(all_items) if ctx["customer_num"] == customer_num), None)
        total_pending = len(all_items)
        if position is None or total_pending == 0:
            position = "?"
            total_pending = "?"
        return {
            "already_enqueued": True,
            "position":         position,
            "total_pending":    total_pending,
        }

    # 2) Redis’e ekle (notification_id'yi de context'e dahil et!)
    context = {
        "customer_num": customer_num,
        "notification_id": notification_id  # Burada ekleniyor!
    }
    rds.sadd(_MINI_RAG_ENQUEUED_SET, customer_num)
    rds.rpush(_MINI_RAG_JOBS_KEY, json.dumps(context))
    total_pending = rds.llen(_MINI_RAG_JOBS_KEY)

    # 3) Notification job’u yarat veya güncelle
    if notification_id is not None and mongo is not None:
        from bson import ObjectId
        notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
        if notif:
            jobs = notif.get("jobs", [])
            for job in jobs:
                if job.get("type") == "mini_rag" and job.get("customer_num") == customer_num:
                    # Job zaten varsa duplicate ekleme!
                    mongo.notifications.update_one(
                        {
                            "_id": ObjectId(notification_id),
                            "jobs.customer_num": customer_num,
                            "jobs.type": "mini_rag",
                        },
                        {
                            "$set": {"jobs.$.updated_at": datetime.utcnow()},
                        }
                    )
                    break
            else:
                # Yoksa ekle
                create_notification_job(
                    mongo=mongo,
                    job_type="mini_rag",
                    notification_id=notification_id,
                    customer_num=customer_num,
                    status="pending"
                )
    return {
        "already_enqueued": False,
        "position":         total_pending,
        "total_pending":    total_pending,
    }

# ────────────────────── CALL-INSIGHTS KUYRUĞU ──────────────────────
def is_call_insights_enqueued(call_id: str) -> bool:
    return rds.sismember(_CALL_INSIGHTS_ENQUEUED_SET, call_id)


def mark_call_insights_enqueued(call_id: str) -> None:
    rds.sadd(_CALL_INSIGHTS_ENQUEUED_SET, call_id)
    rds.rpush(_CALL_INSIGHTS_JOBS_KEY, call_id)


def enqueue_call_insights(call_ids: List[str]) -> Dict[str, int | list | dict]:
    """
    • Yoksa liste sonuna ekler, varsa olduğu gibi bırakır.
    • Hem sayısal özet hem de ayrıntılı ID listeleri döner.
    """
    new_items:      list[str] = []
    already_items:  list[str] = []
    positions:      dict[str, int | None] = {}

    for cid in call_ids:
        if is_call_insights_enqueued(cid):
            already_items.append(cid)
        else:
            mark_call_insights_enqueued(cid)
            new_items.append(cid)

        positions[cid] = _queue_position(_CALL_INSIGHTS_JOBS_KEY, cid)

    all_queued = [x.decode() for x in rds.lrange(_CALL_INSIGHTS_JOBS_KEY, 0, -1)]
    return {
        "newly_enqueued":     len(new_items),
        "already_enqueued":   len(already_items),
        "new_items":          new_items,
        "already_items":      already_items,
        "positions":          positions,
        "all_queued":         all_queued,
    }

# ———————————————————————————————— AUDIO FEATURES KUYRUĞU ————————————————————————————

def is_audio_features_enqueued(call_id: str) -> bool:
    return rds.sismember(_AUDIO_FEATURES_ENQUEUED_SET, call_id)

def mark_audio_features_enqueued(call_id: str) -> None:
    rds.sadd(_AUDIO_FEATURES_ENQUEUED_SET, call_id)
    rds.rpush(_AUDIO_FEATURES_JOBS_KEY, call_id)

def dequeue_audio_features(call_id: str) -> None:
    rds.srem(_AUDIO_FEATURES_ENQUEUED_SET, call_id)

def _queue_position(key: str, item: str) -> int | None:
    raw = rds.lrange(key, 0, -1)
    try:
        return raw.index(item.encode()) + 1
    except ValueError:
        return None

def enqueue_audio_features(call_ids: List[str]) -> Dict[str, int | list | dict]:
    new_items:      list[str] = []
    already_items:  list[str] = []
    positions:      dict[str, int | None] = {}

    for cid in call_ids:
        if is_audio_features_enqueued(cid):
            already_items.append(cid)
        else:
            mark_audio_features_enqueued(cid)
            new_items.append(cid)

        positions[cid] = _queue_position(_AUDIO_FEATURES_JOBS_KEY, cid)

    all_queued = [x.decode() for x in rds.lrange(_AUDIO_FEATURES_JOBS_KEY, 0, -1)]
    return {
        "newly_enqueued":     len(new_items),
        "already_enqueued":   len(already_items),
        "new_items":          new_items,
        "already_items":      already_items,
        "positions":          positions,
        "all_queued":         all_queued,
    }
