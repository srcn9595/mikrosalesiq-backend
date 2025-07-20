from __future__ import annotations

"""insight_sync_worker.py – Senkron Insight üretimi (v5)
========================================================
• Mongo pipeline (veya doğrudan docs) → **LLM (run_llm)** → JSON output
• Langfuse span açar; docs sayısı ve hatalar dahil loglar
• OpenAI bağımlılığı yalnızca `insight_utils.run_llm` içinde
"""

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

import pymongo
from dotenv import load_dotenv
from langfuse import Langfuse

from insight_engine.insight_utils import (
    build_insight_messages,
    format_insight_output,
    run_llm,
)

load_dotenv()
log = logging.getLogger("insight_sync_worker")

# ─────────── ENV ───────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
MAX_DOCS = int(os.getenv("INSIGHT_MAX_DOCS", "300"))
MIN_CAP = int(os.getenv("INSIGHT_MIN_CAP", "1")) 

# ─────────── Clients ───────────
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)

_default_mongo = pymongo.MongoClient(MONGO_URI)[MONGO_DB]

# ─────────── Core func ───────────

def insight_sync_worker(
    *,
    pipeline: Sequence[Dict[str, Any]] | None = None,
    collection: Optional[str] = None,
    docs: Optional[List[Dict[str, Any]]] = None,
    intent: str,
    query: Optional[str] = None,
    mongo=None,
) -> Dict[str, Any]:
    """Senkron insight üretir."""

    if docs is None and (not pipeline or not collection):
        log.error("Eksik parametreler: docs veya (pipeline + collection) zorunlu")
        raise ValueError("docs veya (pipeline + collection) vermek zorunlu")

    mongo = mongo if mongo is not None else _default_mongo

    if docs is None:
        log.info("Mongo aggregate → collection=%s", collection)
        try:
            docs = list(mongo[collection].aggregate(list(pipeline)))  # type: ignore[arg-type]
        except Exception as e:
            log.error(f"Mongo aggregation hatası: {e}")
            return {"message": "⚠️ MongoDB aggregation hatası."}

    if not docs:
        log.warning("Veri bulunamadı, kriterlere uygun döküman yok.")
        return {"items": [], "note": "⚠️ Analiz için yeterli veri bulunamadı."}


    # Token güvenliği: Env ile konfigüre edilebilir üst limit
    sample_docs = docs[: min(len(docs), MAX_DOCS)]
    messages = build_insight_messages(
        sample_docs, intent=intent, query=query, pipeline=pipeline
    )

    try:
        with langfuse.start_as_current_span(
            name="insight_sync_worker",
            input={
                "intent": intent,
                "query": query,
                "docs": len(sample_docs),
            },
            metadata={"component": "insight_sync_worker"},
        ) as span:
            llm_resp = run_llm(messages)

            # Hata kontrolü standardize: run_llm {'error': '...'} döner
            if llm_resp.get("error"):
                err_msg = llm_resp["error"]
                log.error(f"LLM hata: {err_msg}")
                span.update(output={"error": err_msg})
                return {"message": f"❌ {err_msg}"}

            output = format_insight_output(llm_resp)
            if len(docs) < MIN_CAP:
                output["note"] = f"⚠️ Minimum analiz kaydı ({MIN_CAP}) sağlanamadı, yalnızca {len(docs)} kayıt üzerinden analiz yapılmıştır."    
            span.update(output=output)
            return output
    except Exception as e:
        log.exception("Senkron insight üretme sırasında beklenmedik hata.")
        return {"message": "⚠️ Senkron insight üretme hatası."}
