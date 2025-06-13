import os
import redis
from typing import List, Dict

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
rds = redis.from_url(REDIS_URL)

_DOWNLOAD_JOBS_KEY          = "download_jobs"
_DOWNLOAD_ENQUEUED_SET      = "download_enqueued_set"
_CALL_INSIGHTS_JOBS_KEY     = "call_insights_jobs"
_CALL_INSIGHTS_ENQUEUED_SET = "call_insights_enqueued_set"
_MINI_RAG_JOBS_KEY          = "mini_rag_jobs"


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


# ────────────────────── DOWNLOAD KUYRUĞU ──────────────────────
def is_download_enqueued(call_id: str) -> bool:
    return rds.sismember(_DOWNLOAD_ENQUEUED_SET, call_id)


def mark_download_enqueued(call_id: str) -> None:
    rds.sadd(_DOWNLOAD_ENQUEUED_SET, call_id)
    rds.rpush(_DOWNLOAD_JOBS_KEY, call_id)


def enqueue_downloads(call_ids: List[str]) -> Dict[str, int | list | dict]:
    newly, already = 0, 0
    positions: dict[str, int | None] = {}

    for cid in call_ids:
        if is_download_enqueued(cid):
            already += 1
        else:
            mark_download_enqueued(cid)
            newly += 1

        positions[cid] = _queue_position(_DOWNLOAD_JOBS_KEY, cid)

    all_queued = [x.decode() for x in rds.lrange(_DOWNLOAD_JOBS_KEY, 0, -1)]
    return {
        "newly_enqueued": newly,
        "already_enqueued": already,
        "positions": positions,        #  ➡️  YENİ
        "all_queued": all_queued
    }


# ────────────────────── MINI-RAG KUYRUĞU ──────────────────────
def is_mini_rag_enqueued(customer_num: str) -> bool:
    return customer_num.encode() in rds.lrange(_MINI_RAG_JOBS_KEY, 0, -1)


def enqueue_mini_rag(customer_num: str) -> dict:
    """
    • Redis kuyruğuna ekler (zaten eklendiyse position’ı hesaplar).
    • Her durumda
        { "position": X, "total_pending": Y, "already_enqueued": bool }
      şeklinde bilgi döner.
    """
    # Kuyruğun mevcut hali
    raw = rds.lrange(_MINI_RAG_JOBS_KEY, 0, -1)
    encoded = customer_num.encode()

    if encoded in raw:                            # zaten sırada
        pos = raw.index(encoded) + 1
        return {
            "position": pos,
            "total_pending": len(raw),
            "already_enqueued": True
        }

    # Yeni enqueue
    rds.rpush(_MINI_RAG_JOBS_KEY, customer_num)
    new_total = len(raw) + 1
    return {
        "position": new_total,                    # listenin sonuna eklendi
        "total_pending": new_total,
        "already_enqueued": False
    }




# ────────────────────── CALL-INSIGHTS KUYRUĞU ──────────────────────
def is_call_insights_enqueued(call_id: str) -> bool:
    return rds.sismember(_CALL_INSIGHTS_ENQUEUED_SET, call_id)


def mark_call_insights_enqueued(call_id: str) -> None:
    rds.sadd(_CALL_INSIGHTS_ENQUEUED_SET, call_id)
    rds.rpush(_CALL_INSIGHTS_JOBS_KEY, call_id)


def enqueue_call_insights(call_ids: List[str]) -> Dict[str, int | list | dict]:
    newly, already = 0, 0
    positions: dict[str, int | None] = {}

    for cid in call_ids:
        if is_call_insights_enqueued(cid):
            already += 1
        else:
            mark_call_insights_enqueued(cid)
            newly += 1

        positions[cid] = _queue_position(_CALL_INSIGHTS_JOBS_KEY, cid)

    all_queued = [x.decode() for x in rds.lrange(_CALL_INSIGHTS_JOBS_KEY, 0, -1)]
    return {
        "newly_enqueued": newly,
        "already_enqueued": already,
        "positions": positions,        #  ➡️  YENİ
        "all_queued": all_queued
    }
