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
_MINI_RAG_ENQUEUED_SET    = "mini_rag_enqueued_set"

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
    """
    • Yoksa liste sonuna ekler, varsa olduğu gibi bırakır.
    • Hem sayısal özet hem de ayrıntılı ID listeleri döner.
    """
    new_items:      list[str] = []
    already_items:  list[str] = []
    positions:      dict[str, int | None] = {}

    for cid in call_ids:
        if is_download_enqueued(cid):
            already_items.append(cid)
        else:
            mark_download_enqueued(cid)
            new_items.append(cid)

        positions[cid] = _queue_position(_DOWNLOAD_JOBS_KEY, cid)

    all_queued = [x.decode() for x in rds.lrange(_DOWNLOAD_JOBS_KEY, 0, -1)]
    return {
        # eski alanlar — geriye dönük uyumluluk
        "newly_enqueued":     len(new_items),
        "already_enqueued":   len(already_items),
        # yeni alanlar
        "new_items":          new_items,
        "already_items":      already_items,
        # yardımcı
        "positions":          positions,
        "all_queued":         all_queued,
    }


# ────────────────────── MINI-RAG KUYRUĞU ──────────────────────
def is_mini_rag_enqueued(customer_num: str) -> bool:
    return rds.sismember(_MINI_RAG_ENQUEUED_SET, customer_num)


def enqueue_mini_rag(customer_num: str) -> dict:
    if is_mini_rag_enqueued(customer_num):
        position      = _queue_position(_MINI_RAG_JOBS_KEY, customer_num)
        total_pending = rds.llen(_MINI_RAG_JOBS_KEY)
        return {
            "already_enqueued": True,
            "position":         position,
            "total_pending":    total_pending,
        }

    # yeni ekle
    rds.sadd(_MINI_RAG_ENQUEUED_SET, customer_num)
    rds.rpush(_MINI_RAG_JOBS_KEY,    customer_num)

    total_pending = rds.llen(_MINI_RAG_JOBS_KEY)
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
