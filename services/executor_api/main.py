#!/usr/bin/env python3
# services/executor_api/main.py

from fastapi import FastAPI, HTTPException, Body, Path
import os
import logging
import redis
import pymongo
from typing import Any, Dict, List
from queue_utils import enqueue_mini_rag
from fastapi.responses import JSONResponse
from bson import json_util
import json
from queue_utils import is_mini_rag_enqueued
from mini_rag.mini_rag_sync_worker import generate_mini_rag_output 
import mongo_utils
import queue_utils
from clean_transcript.clean_sync_worker import clean_transcript_sync
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

# “audio_jobs” koleksiyonunu hem status hem transcript alanlarında kullanıyoruz
audio_coll = db["audio_jobs"]

app = FastAPI()

def bson_safe(obj):
    """MongoDB BSON verisini güvenli şekilde JSON'a çevirir."""
    return json.loads(json_util.dumps(obj))

@app.post("/enqueue-calls")
async def enqueue_calls_endpoint(payload: Dict[str, Any] = Body(...)):
    """
    Yeni bir enqueue isteği geldiğinde:
    1) call_records’dan agent_email + tarih aralığına göre kayıtları çeker,
    2) Eğer call_ids verildiyse sadece onlara filtre yapar,
    3) audio_jobs koleksiyonuna ekler (yeni eklenenleri ‘queued’ yapar),
    4) Yeni eklenen call_id’leri Redis ‘download_jobs’ kuyruğuna atar,
    5) Temsilcinin (agent_email) hâlihazırdaki ‘cleaned’ ve ‘waiting’ durumlarını döner.
    """
    agent_email  = payload.get("agent_email")
    customer_num = payload.get("customer_num")
    call_ids     = payload.get("call_ids", [])
    start_date   = payload.get("start_date")  # “YYYY-MM-DD” veya None
    end_date     = payload.get("end_date")    # “YYYY-MM-DD” veya None

    if not agent_email or not customer_num:
        raise HTTPException(400, "agent_email ve customer_num alanları zorunlu.")

    # 1) call_records’dan ilgili kayıtları çek
    try:
        records: List[Dict[str, Any]] = mongo_utils.get_calls_from_call_records(
            agent_email=agent_email,
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        log.error("call_records sorgu hatası: %s", e)
        raise HTTPException(500, f"call_records sorgu hatası: {e}")

    # 2) Eğer explicit call_ids geldiyse, sadece onlar üzerinden filtrele
    if call_ids:
        rec_map = {r["call_id"]: r for r in records}
        records = [rec_map[cid] for cid in call_ids if cid in rec_map]

    if not records:
        return {
            "result": {
                "found_calls": [],
                "cleaned":      [],
                "waiting":      [],
                "enqueue_stats": {"newly": 0, "existing": 0},
                "message":      "Belirtilen kriterlere uygun çağrı bulunamadı."
            }
        }

    # 3) audio_jobs koleksiyonuna ekle
    try:
        add_res = mongo_utils.add_new_calls_to_customer(customer_num, records)
    except ValueError as e:
        log.error("audio_jobs ekleme hatası: %s", e)
        raise HTTPException(400, str(e))

    newly_call_ids = add_res.get("inserted", [])
    enqueue_res    = queue_utils.enqueue_downloads(newly_call_ids)

    # 4) Temsilcinin (agent_email) güncel “cleaned” ve “waiting” listelerini al
    agent_status = mongo_utils.get_audio_jobs_for_agent(agent_email)

    return {
        "result": {
            "found_calls":   records,
            "cleaned":       agent_status["cleaned"],
            "waiting":       agent_status["waiting"],
            "enqueue_stats": {
                "newly":    enqueue_res["newly_enqueued"],
                "existing": enqueue_res["already_enqueued"]
            }
        }
    }


@app.get("/transcript/by-call/{call_id}")
async def get_transcript_by_call(call_id: str = Path(..., description="Şu çağrının transkriptini getir")):
    """
    Tek bir call_id için:
      - Eğer status == "cleaned" ise → temizlenmiş metni döner.
      - Aksi halde 400 hatası (henüz pipeline’a atılmamış veya indirilen ama temizlenmemiş).
      - Bulunamazsa 404 hatası.
    """
    doc = audio_coll.find_one({"calls.call_id": call_id}, {"calls.$": 1})
    if not doc or not doc.get("calls"):
        raise HTTPException(404, f"call_id '{call_id}' bulunamadı.")

    call_obj = doc["calls"][0]
    status   = call_obj.get("status")

    if status == "cleaned":
        return {
            "call_id":    call_id,
            "call_date":  call_obj.get("call_date"),
            "transcript": call_obj.get("cleaned_transcript", "")
        }
    else:
        raise HTTPException(
            400,
            f"call_id '{call_id}' henüz temizlenmemiş (status: {status})."
        )


@app.get("/transcript/by-customer/{customer_num}")
async def get_all_transcripts_by_customer(
    customer_num: str = Path(..., description="Müşteri numarasını girin")
):
    """
    Bir müşteri numarasındaki tüm çağrıları kontrol eder:
      1) Eğer status == "cleaned" ise → temiz transcript’i toplar.
      2) Diğer status’ler (queued/downloaded/transcribed) için → call_id’leri `to_enqueue` listesine ekler.
      3) `to_enqueue` içindekileri Redis ‘download_jobs’ kuyruğuna atar (zaten ekli olmayabilir).
    Dönüş JSON’u:
    {
      "customer_num":         "...",
      "cleaned_transcripts":  [ {call_id, call_date, transcript}, … ],
      "to_enqueue":           [ … ],
      "enqueue_stats":        { "newly_enqueued": X, "already_enqueued": Y, "all_queued": […] }
    }
    """
    doc = audio_coll.find_one({"customer_num": customer_num})
    if not doc:
        raise HTTPException(404, f"customer_num '{customer_num}' için audio_jobs kaydı yok.")

    cleaned_transcripts = []
    to_enqueue          = []

    for call in doc.get("calls", []):
        cid    = call.get("call_id")
        status = call.get("status")
        if status == "cleaned":
            cleaned_transcripts.append({
                "call_id":    cid,
                "call_date":  call.get("call_date"),
                "transcript": call.get("cleaned_transcript", "")
            })
        else:
            to_enqueue.append(cid)

    if to_enqueue:
        enqueue_res = queue_utils.enqueue_downloads(to_enqueue)
        log.info(f"{customer_num} için eksik call_id’ler download kuyruğuna atıldı: {enqueue_res}")
    else:
        enqueue_res = {"newly_enqueued": 0, "already_enqueued": 0, "all_queued": []}

    return {
        "customer_num":        customer_num,
        "cleaned_transcripts": cleaned_transcripts,
        "to_enqueue":          to_enqueue,
        "enqueue_stats":       enqueue_res
    }


# ───────────────────────────── YENİ: /execute ENDPOINT ─────────────────────────────
@app.post("/execute")
async def execute_plan(plan: List[Dict[str, Any]] = Body(...)):
    """
    • mongo_aggregate çıktısındaki her çağrı için:
        1) cleaned_transcript varsa → dokunma.
        2) yoksa koleksiyondan lookup yap → varsa ekle.
        3) hâlâ yok ama transcript var → clean_transcript_sync ile anında temizle.
        4) hâlâ yok (transcript de yok) → download kuyruğuna at.
    • Yalnız mongo_aggregate istenmişse (başka tool yoksa) sonucu hemen döndürür.
    • get_mini_rag_summary → 4 adımlı senkron mantık (varsa döndür / üret / temizle / kuyruğa at).
    """
    try:
        log.info("execute_plan çağrıldı. Plan: %s", plan)

        # ───────────── get_mini_rag_summary (çoklu & senkron) ─────────────
        summary_steps = [s for s in plan if s.get("name") == "get_mini_rag_summary"]
        if summary_steps:
            results   : list[dict] = []
            queue_msgs: list[str]  = []

            # ❶ customer_num veya customer_nums (liste) normalize et
            customer_set: set[str] = set()
            for st in summary_steps:
                arg = st.get("arguments", {})
                if "customer_num" in arg:
                    customer_set.add(arg["customer_num"])
                if "customer_nums" in arg:
                    customer_set.update(arg["customer_nums"])

            for cnum in customer_set:
                doc = audio_coll.find_one({"customer_num": cnum})
                if not doc:
                   results.append({"name":"get_mini_rag_summary",
                                   "output":{"message":f"{cnum} için kayıt yok"}})
                   continue

                # ➋ Özet zaten varsa
                if doc.get("mini_rag", {}).get("summary"):
                   results.append({"name":"get_mini_rag_summary",
                                   "output":doc["mini_rag"]})
                   continue

                # ➌ Eksik cleaned → varsa sync temizle
                for c in doc["calls"]:
                   if not c.get("cleaned_transcript") and c.get("transcript"):
                      try:
                        clean_transcript_sync(c["call_id"])
                      except Exception as e:
                        log.warning("clean fail %s: %s", c["call_id"], e)

                # ➍ Temizlik sonrası özet üretebilir miyiz?
                if any(c.get("cleaned_transcript") for c in
                       audio_coll.find_one({"customer_num":cnum},
                                           {"calls.cleaned_transcript":1})["calls"]):
                   try:
                       parsed = generate_mini_rag_output(cnum)
                       results.append({"name":"get_mini_rag_summary","output":parsed})
                       continue
                   except Exception as ex:
                      log.error("miniRAG %s err: %s", cnum, ex)

                # ➎ Hiç transcript yok → kuyruk bilgisi
                q = queue_utils.enqueue_mini_rag(cnum)
                status = "zaten sırada" if q["already_enqueued"] else "kuyruğa eklendi"
                queue_msgs.append(f"{cnum} {status} "
                                  f"({q['position']}/{q['total_pending']})")

              # Eğer en az bir summary üretebildiysek client’a döndür
            if results:
              return JSONResponse(content={"results": results})

                  # Aksi hâlde yalnızca kuyruk mesajları kalmışsa
            return {"message": " | ".join(queue_msgs)
                   or "İşlenebilecek müşteri bulunamadı"}
        # ───────────────────────────────────────────────────────────────────


        # ───────────── mongo_aggregate adımı zorunlu ──────────────
        mongo_steps = [s for s in plan if s.get("name") == "mongo_aggregate"]
        if not mongo_steps:
            raise HTTPException(400, "execute plan’ında 'mongo_aggregate' adımı yok.")

        mongo_step   = mongo_steps[0]
        args         = mongo_step.get("arguments", {})
        coll_name    = args.get("collection")
        pipeline     = args.get("pipeline", [])

        if not coll_name or not isinstance(pipeline, list):
            raise HTTPException(400, f"Geçersiz mongo_aggregate argümanları: {args}")

        # Agent e-mail'de geniş regex koruması
        if any("$match" in st and "calls.agent_email" in st["$match"]
               and isinstance(st["$match"]["calls.agent_email"], dict)
               and "$regex" in st["$match"]["calls.agent_email"] for st in pipeline):
            return {"message": "Agent e-mail için regex içeren sorgular desteklenmiyor."}

        docs = list(db[coll_name].aggregate(pipeline))
        if not docs:
            return {"message": "Girilen kriterlere uygun kayıt bulunamadı."}

        # 1· lookup → 2· senkron clean → 3· enqueue eksikler
        need_lookup = [d for d in docs if not d.get("cleaned_transcript")]
        if need_lookup:
            ids = [d["call_id"] for d in need_lookup]
            cursor = audio_coll.aggregate([
                {"$unwind": "$calls"},
                {"$match": {"calls.call_id": {"$in": ids}}},
                {"$project": {
                    "_id": 0,
                    "call_id": "$calls.call_id",
                    "cleaned_transcript": "$calls.cleaned_transcript",
                    "transcript":         "$calls.transcript"
                }}
            ])
            lut = {c["call_id"]: c for c in cursor}
            for d in need_lookup:
                extra = lut.get(d["call_id"], {})
                d.setdefault("cleaned_transcript", extra.get("cleaned_transcript"))
                d.setdefault("transcript",         extra.get("transcript"))

        to_clean = [d for d in docs if d.get("transcript") and not d.get("cleaned_transcript")]
        for rec in to_clean:
            try:
                rec["cleaned_transcript"] = clean_transcript_sync(rec["call_id"])
                log.info("call_id %s senkron temizlendi.", rec["call_id"])
            except Exception as e:
                log.warning("call_id %s temizlenemedi: %s", rec["call_id"], e)

        missing_call_ids = [d["call_id"] for d in docs if not d.get("cleaned_transcript")]
        if missing_call_ids:
            queue_utils.enqueue_downloads(missing_call_ids)

        requested_tools = {s.get("name") for s in plan}
        if requested_tools == {"mongo_aggregate"}:
            return JSONResponse(content={
                "results": [{"name": "mongo_aggregate", "output": bson_safe(docs)}]
            })

        # ─────────── call_insights kuyruğu ────────────
        if "call_insights" in requested_tools:
            not_scored = [
                d["call_id"] for d in docs
                if not db["call_insights"].find_one({"call_id": d["call_id"]})
            ]
            if not_scored:
                info = queue_utils.enqueue_call_insights(not_scored)
                queued_msg = (f"{info['newly_enqueued']} yeni, "
                              f"{info['already_enqueued']} zaten vardı "
                              f"(toplam sıra={len(info['all_queued'])}).")
                return {"message": f"call_insights kuyruğa alındı: {queued_msg}"}

        # ───────────── mini_rag kuyruğu (YENİ) ─────────────
        if "mini_rag" in requested_tools:
            customer_nums = {d.get("customer_num") for d in docs if d.get("customer_num")}
            if customer_nums:
                msgs = []
                for cnum in customer_nums:
                    rec = db["audio_jobs"].find_one(
                        {"customer_num": cnum}, {"mini_rag.summary": 1}
                    )
                    if rec and rec.get("mini_rag", {}).get("summary"):
                        continue  # zaten var
                    qinfo = queue_utils.enqueue_mini_rag(cnum)
                    status = "zaten sırada" if qinfo["already_enqueued"] else "kuyruğa eklendi"
                    msgs.append(f"{cnum} {status} ({qinfo['position']}/{qinfo['total_pending']})")
                if msgs:
                    return {"message": " | ".join(msgs)}

        # Eksik transcript + analiz istenirken
        if {"call_insights", "mini_rag"} & requested_tools and missing_call_ids:
            return {"message": f"{len(missing_call_ids)} çağrının cleaned_transcript "
                               "verisi eksik. Kuyruğa alındı. "
                               "Lütfen birkaç dakika sonra tekrar deneyin."}

        # Varsayılan dönüş
        return JSONResponse(content={
            "results": [{"name": "mongo_aggregate", "output": bson_safe(docs)}]
        })

    except HTTPException as he:
        raise he
    except Exception as ex:
        log.error("execute_plan genel hata: %s", ex)
        raise HTTPException(500, "Sunucu tarafında beklenmeyen bir hata oluştu.")

