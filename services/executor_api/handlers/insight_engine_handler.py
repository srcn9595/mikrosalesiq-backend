from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Set
from datetime import datetime

from pymongo import MongoClient
from qdrant_client import QdrantClient

from customer_embedding.embedding_utilts import get_customer_embedding
from insight_engine.insight_sync_worker import insight_sync_worker
from queue_utils import enqueue_downloads, enqueue_insight_engine, enqueue_mini_rag

log = logging.getLogger("insight_engine_handler")

try:
    import dateutil.parser
except ImportError:
    dateutil = None

# ── Fallback connections ──
_default_mongo = (
    MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))[
        os.getenv("MONGO_DB", "mikrosalesiq")
    ]
)
_qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", "6333")),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def patch_dates_in_pipeline(pipeline, date_fields=["close_date", "created_at", "updated_at"]):
    for step in pipeline:
        if "$match" in step:
            for field in date_fields:
                if field in step["$match"]:
                    field_val = step["$match"][field]
                    for op in ["$gte", "$lte"]:
                        val = field_val.get(op)
                        if isinstance(val, str):
                            try:
                                if dateutil:
                                    field_val[op] = dateutil.parser.parse(val)
                                else:
                                    field_val[op] = datetime.fromisoformat(val)
                            except Exception as e:
                                print(f"Date parse failed: {val} -> {e}")
    return pipeline

def _pipeline_requests_text(ppl: List[Dict[str, Any]]) -> bool:
    return any(
        st.get("$project") and any(k.endswith("transcript") for k in st["$project"] if st["$project"][k])
        for st in ppl
    )

def _pipeline_requests_mini_rag(ppl: List[Dict[str, Any]]) -> bool:
    return any(
        st.get("$project") and any(k.startswith("mini_rag") or k.startswith("customer_profile") for k in st["$project"] if st["$project"][k])
        for st in ppl
    )

# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
async def insight_engine_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Toplu insight üretiminde:
    - Yalnızca summary'si dolu olan kayıtlarla analiz yapar.
    - Eksik (mini_rag.summary boş) olanları atlar, kuyruğa eklemez.
    - Yeterli veri yoksa uyarı mesajı döner.
    """
    query: str = args.get("query", "").strip()
    top_k = args.get("top_k")
    threshold = args.get("threshold")
    pipeline: List[Dict[str, Any]] = args.get("pipeline", [])
    collection: str = args.get("collection") or "audio_jobs"
    intent: Optional[str] = args.get("intent")
    mongo_param = args.get("mongo")
    mongo = mongo_param if mongo_param is not None else _default_mongo

    if not intent:
        log.error("Intent missing: %s", intent)
        return _err("intent zorunlu")
    if not pipeline:
        log.error("Pipeline missing for intent: %s", intent)
        return _err("pipeline zorunlu (en az $match)")

    # 1) Mongo aggregate (pre-filter)
    try:
        pipeline = patch_dates_in_pipeline(pipeline)
        log.info(f"Patched pipeline: {json.dumps(pipeline, default=str, ensure_ascii=False)}")
        docs = list(mongo[collection].aggregate(pipeline))
    except Exception as e:
        log.exception("Mongo aggregation error")
        return _err(f"Mongo hata: {e}")

    if not docs:
        log.warning("Veri bulunamadı, kriterlere uygun döküman yok.")
        return _err("Girilen kriterlere uygun kayıt bulunamadı.")

    # 2) Qdrant daraltması (varsa)
    if query and top_k is not None and threshold is not None:
        try:
            vec = get_customer_embedding(query)
            if vec is not None:
                res = _qdrant.search(
                    collection_name="customer_profiles",
                    query_vector=vec,
                    limit=top_k,
                    score_threshold=threshold,
                )
                qdrant_nums = [r.payload["customer_num"] for r in res if r.payload and "customer_num" in r.payload]
                if qdrant_nums:
                    docs = [d for d in docs if d.get("customer_num") in qdrant_nums]
        except Exception as e:
            log.warning(f"Qdrant search failed: {e}")

    if not docs:
        log.warning("Qdrant daraltmasından sonra veri kalmadı.")
        return _err("Girilen kriterlere uygun kayıt bulunamadı (Qdrant daralttı).")

    # 3) Sadece summary'si dolu olanlarla devam!
    filtered_docs = [d for d in docs if d.get("mini_rag", {}).get("summary")]
    missing = [d.get("customer_num") for d in docs if not d.get("mini_rag", {}).get("summary")]
    log.info(f"Aggregate sonrası toplam kayıt: {len(docs)}")
    log.info(f"Summary dolu olanlar: {len(filtered_docs)}")
    if missing:
        log.info(f"Summary'si dolu olmayan kayıtlar: {missing}")
    if not filtered_docs:
        log.warning("Summary'si dolu kayıt yok.")
        return _err("Analiz için yeterli summary'si dolu veri bulunamadı.")

    if not filtered_docs:
        log.warning("Summary’si dolu kayıt yok.")
        return _err("Analiz için yeterli summary’si dolu veri bulunamadı.")

    # 4) Senkron insight
    try:
        output = insight_sync_worker(
            docs=filtered_docs,
            pipeline=pipeline,
            collection=collection,
            intent=intent,
            query=query,
            mongo=mongo,
        )
    except Exception as e:
        log.exception("sync_worker fail")
        return _err(f"sync_worker hata: {e}")

    log.info("Senkron insight üretildi.")
    return {"name": "insight_engine", "output": {"items": [output]}}

# ---------------------------------------------------------------------------
# Error wrapper
# ---------------------------------------------------------------------------

def _err(note: str) -> Dict[str, Any]:
    log.error(f"Error: {note}")
    return {"name": "insight_engine", "output": {"items": [], "note": note}}
