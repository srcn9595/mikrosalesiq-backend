from __future__ import annotations

"""insight_async_worker.py – Queue-tüketen arka-plan servis (v3)
================================================================
• Redis kuyruğu: `_INSIGHT_ENGINE_JOBS_KEY`
• mini_rag veya transcript eksikse job’u back-off ile sıraya geri atar (max RETRIES)
• Veri tamamsa `insight_sync_worker` çağırır, Mongo’ya kaydeder & notification günceller
"""

import json
import logging
import os
import time
from typing import Any, Dict, List

import pymongo
from dotenv import load_dotenv
from langfuse import Langfuse

# Local helpers
from queue_utils import (
    _INSIGHT_ENGINE_ENQUEUED_SET,
    _INSIGHT_ENGINE_JOBS_KEY,
    rds,
)
from insight_engine.insight_sync_worker import insight_sync_worker
from shared_lib.notification_utils import (
    finalize_notification_if_ready,
    update_job_in_notification,
)

load_dotenv()
log = logging.getLogger("insight_async_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ─────────── ENV
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
QUEUE_NAME = os.getenv("INSIGHT_ENGINE_QUEUE", _INSIGHT_ENGINE_JOBS_KEY)
MAX_RETRIES = int(os.getenv("INSIGHT_MAX_RETRIES", "5"))

# ─────────── Clients
mongo_client = pymongo.MongoClient(MONGO_URI)
_db = mongo_client[MONGO_DB]
_audio_jobs = _db["audio_jobs"]
_insights = _db["insight_outputs"]

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _customer_ready(customer_num: str) -> bool:
    doc = _audio_jobs.find_one({"customer_num": customer_num})
    return bool(doc and doc.get("mini_rag", {}).get("summary"))

def _backoff_sleep(retries: int) -> None:
    sleep_sec = min(2 ** retries, 30)  # cap at 30 s
    time.sleep(sleep_sec)

# ---------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------

def run() -> None:
    log.info("Insight-engine async worker started.")
    while True:
        raw = rds.rpop(QUEUE_NAME)
        if not raw:
            time.sleep(3)
            continue

        try:
            ctx: Dict[str, Any] = json.loads(raw.decode())
            cnum: str = ctx["customer_num"]
            query: str | None = ctx.get("query")
            pipeline: List[Dict[str, Any]] = ctx.get("pipeline", [])
            notification_id: str | None = ctx.get("notification_id")
            intent: str = ctx.get("intent", "insight_async")
            retries: int = ctx.get("retries", 0)
        except Exception as e:
            log.error("Job parse hatası: %s", e)
            continue

        # mini_rag hazır değilse yeniden kuyruğa at (back-off)
        if not _customer_ready(cnum):
            if retries >= MAX_RETRIES:
                log.error("%s mini_rag hâlâ yok; max retries aşıldı, job drop.", cnum)
                continue
            ctx["retries"] = retries + 1
            rds.lpush(QUEUE_NAME, json.dumps(ctx))
            log.info("%s için mini_rag yok – retry %d/%d", cnum, retries + 1, MAX_RETRIES)
            _backoff_sleep(retries)
            continue

        # Senkron insight üret
        start_time = time.time()  # Başlangıç zamanını kaydet
        with langfuse.start_as_current_span(
            name="insight_async_worker",
            input={"customer_num": cnum, "query": query, "intent": intent},
            metadata={"component": "insight_async_worker"},
        ) as span:
            try:
                result = insight_sync_worker(
                    pipeline=pipeline,
                    collection="audio_jobs",
                    intent=intent,
                    query=query,
                    mongo=_db,
                )
            except Exception as e:
                log.error("Senkron insight üretme hatası: %s", e)
                result = {"error": f"Insight üretimi sırasında hata oluştu: {str(e)}"}
            span.update(output=result)

        # Mongo’ya yaz
        _insights.update_one(
            {"customer_num": cnum},
            {"$set": {"last_output": result, "updated_at": time.time()}},
            upsert=True,
        )

        rds.srem(_INSIGHT_ENGINE_ENQUEUED_SET, cnum)
        elapsed_time = time.time() - start_time  # İşlem süresi
        log.info("✅ Insight tamam: %s (%.2f saniye)", cnum, elapsed_time)

        # Bildirim güncelle
        if notification_id:
            try:
                update_job_in_notification(
                    mongo=_db,
                    notification_id=notification_id,
                    customer_num=cnum,
                    job_status="done",
                    result=result,
                )
                finalize_notification_if_ready(_db, notification_id)
            except Exception as e:
                log.error("Bildirim güncellenirken hata: %s", e)


if __name__ == "__main__":
    run()
