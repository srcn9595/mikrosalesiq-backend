#!/usr/bin/env python3
# services/executor_api/main.py

from fastapi import FastAPI, HTTPException, Body, Path
import os
import logging
import redis
import pymongo
from typing import Any, Dict, List
from fastapi.responses import JSONResponse
from bson import json_util
import json
from mini_rag.mini_rag_sync_worker import generate_mini_rag_output 
import mongo_utils
import queue_utils
from clean_transcript.clean_sync_worker import clean_transcript_sync
import re
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

from handlers.mini_rag_sync_handler import sync_mini_rag_summary_handler
from handlers.get_call_metrics_handler import get_call_metrics_handler
from handlers.mini_rag_async_handler import mini_rag_async_handler
from handlers.mongo_aggregate_handler import mongo_aggregate_handler
from handlers.vector_call_handler import vector_call_handler
from handlers.vector_customer_handler import vector_customer_handler
from handlers.insight_engine_handler import insight_engine_handler

from shared_lib.notification_utils import create_notification

# ───────────── prev-placeholder helper’ları ─────────────
_PH_RE = re.compile(r"{prev\.([^}]+)}")

def _fill_templates(obj, ctx: dict):
    """
    Dict/list/string içinde geçen  {prev.foo}  şablonlarını
    ctx["foo"] değeriyle değiştirir.
    """
    if isinstance(obj, dict):
        return {k: _fill_templates(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill_templates(v, ctx) for v in obj]
    if isinstance(obj, str):
        return _PH_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), obj)
    return obj

# ───────────────────────────── LOGGING ─────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("executor_api")

# ───────────────────────────── ENV & GLOBALS ─────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DB  = os.getenv("MONGO_DB",  "mikrosalesiq")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

client = pymongo.MongoClient(MONGO_URI)
db     = client[MONGO_DB]
rds    = redis.from_url(REDIS_URL)
mongo     = AsyncIOMotorClient(MONGO_URI)[MONGO_DB]
pymongo_client = pymongo.MongoClient(MONGO_URI)
pymongo_db = pymongo_client[MONGO_DB]

# “audio_jobs” koleksiyonunu hem status hem transcript alanlarında kullanıyoruz
audio_coll = db["audio_jobs"]

app = FastAPI()

def bson_safe(obj):
    """MongoDB BSON verisini güvenli şekilde JSON'a çevirir."""
    return json.loads(json_util.dumps(obj))

def _is_call_level(pipeline: list[dict]) -> bool:
    for st in pipeline:
        if "$unwind" in st and st["$unwind"].startswith("$calls"):
            return True
        for op in ("$project", "$match", "$sort"):
            if op in st and any(k.startswith("calls.") for k in st[op]):
                return True
    return False


# ───────────────────────────── YENİ: /execute ENDPOINT ─────────────────────────────
@app.post("/execute")
async def execute_plan(plan: List[Dict[str, Any]] = Body(...)):
    try:
        log.info("execute_plan çağrıldı. Plan: %s", plan)
        
        # chat_message_id yakala
        chat_message_id = None
        for step in plan:
            if "arguments" in step and "chat_message_id" in step["arguments"]:
                chat_message_id = step["arguments"]["chat_message_id"]
                break

        notif_obj = pymongo_db.notifications.find_one({"chat_message_id": chat_message_id})
        if notif_obj:
            notification_id = str(notif_obj["_id"])
            log.info("Notification bulundu: %s", notification_id)     
        else:
            notification_id = create_notification(
                mongo=pymongo_db,
                notif_type="execute_plan",
                chat_message_id=chat_message_id,
                plan=plan,
                status="pending",
                is_async_process=True,
            )
        log.info(f"Yeni notification yaratıldı: {notification_id}")

        requested_tools = {s.get("name") for s in plan}
        # ───────────── Insight Engine ─────────────
        insight_engine_steps = [s for s in plan if s.get("name") == "insight_engine"]
        if insight_engine_steps:
            results = []
            for step in insight_engine_steps:
                args = step.get("arguments", {}).copy()
                args["intent"] = step.get("intent")
                args["notification_id"] = notification_id
                args["mongo"] = db  # 🔑 mevcut bağlantıyı ekle
                out = await insight_engine_handler(args)
                results.append(out)
    
            # Eğer sonuçlar tamamen boş ya da her biri anlamsız ise error message ile dön
            if (
                not results or 
                all(
                    not (r and isinstance(r, dict) and "output" in r and isinstance(r["output"], dict)) or (
                        not r["output"].get("items") and not r["output"].get("message")
                    )
                    for r in results
                )
            ):
                log.warning("Insight engine sonuçları boş veya geçersiz!")
                return {
                    "results": [{
                        "name": "insight_engine",
                        "output": {"message": "Girilen kriterlere uygun kayıt bulunamadı."}
                    }]
                }
    
            # Buraya düşerse en az bir geçerli output var demek
            return {"results": results}


        # ───────────── Vektör Arama (call-level) ─────────────
        vector_call_steps = [s for s in plan if s.get("name") == "vector_call"]
        if vector_call_steps:
            results = []
            for step in vector_call_steps:
                out = await vector_call_handler(step["arguments"])
                results.append(out)
            if results:
                return {"results": results}

        vector_customer_steps = [s for s in plan if s.get("name") == "vector_customer"]
        if vector_customer_steps:
            results = []
            for step in vector_customer_steps:
                out = await vector_customer_handler(step["arguments"])
                results.append(out)
            if results:
                return {"results": results}    

        # ───────────── get_call_metrics (toplam/ortalama/max süre) ─────────────
        metrics_steps = [s for s in plan if s.get("name") == "get_call_metrics"]
        if metrics_steps:
            results = get_call_metrics_handler(db, metrics_steps)
            if results:
                return {"results": results}

        # ───────────── get_mini_rag_summary (çoklu & senkron) ─────────────
        summary_steps = [s for s in plan if s.get("name") == "get_mini_rag_summary"]
        if summary_steps:
            results = []
            for step in summary_steps:
                args = step.get("arguments", {}).copy()
                args["notification_id"] = notification_id
                out = sync_mini_rag_summary_handler(
                    audio_coll, queue_utils, clean_transcript_sync, generate_mini_rag_output, args
                )
                # Eğer yalnızca "message" alanı varsa, direkt mesaj olarak dön!
                if (
                    isinstance(out, dict)
                    and "output" in out
                    and isinstance(out["output"], dict)
                    and list(out["output"].keys()) == ["message"]
             ):
                    return {"message": out["output"]["message"]}
                results.append(out)
            if results:
                return {"results": results}
        # ───────────────────────────────────────────────────────────────────

        
        # ───────────── mongo_aggregate adımı zorunlu ──────────────
        
        for step in plan:
            if step.get("name") == "mongo_aggregate":
                step.setdefault("arguments", {})
                step["arguments"]["notification_id"] = notification_id


        result, docs, missing_call_ids = mongo_aggregate_handler(
            db, audio_coll, queue_utils, clean_transcript_sync,
            plan, _fill_templates, _is_call_level,
            log, bson_safe, requested_tools
        )
        if isinstance(result, dict) and "message" in result and "results" not in result:
            return JSONResponse(content={"message": result["message"]})


        # ───────────── mini_rag kuyruğu  ─────────────
        if "mini_rag" in requested_tools:
            result = mini_rag_async_handler(db, queue_utils, docs)
            if result:
                return result
        # ───────────────────────────────────────────────────────────────────

        # Varsayılan dönüş
        return JSONResponse(content={
            "results": [{"name": "mongo_aggregate", "output": bson_safe(docs)}]
        })

    except HTTPException as he:
        raise he
    except Exception as ex:
        log.error("execute_plan genel hata: %s", ex)
        raise HTTPException(500, "Sunucu tarafında beklenmeyen bir hata oluştu.")

