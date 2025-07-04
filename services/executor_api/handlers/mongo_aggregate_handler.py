# handlers/mongo_aggregate_handler.py

from fastapi import HTTPException
from fastapi.responses import JSONResponse

def mongo_aggregate_handler(
    db, audio_coll, queue_utils, clean_transcript_sync, plan, _fill_templates, _is_call_level, log, bson_safe, requested_tools
):
    collected_results: list = []
    context: dict = {}
    last_docs = None
    last_missing_call_ids = []

    for step in plan:
        if step.get("name") != "mongo_aggregate":
            continue

        # Şablonları doldur
        step["arguments"] = _fill_templates(step["arguments"], context)
        coll_name = step["arguments"].get("collection")
        pipeline  = step["arguments"].get("pipeline")
        call_level = _is_call_level(pipeline)

        if not coll_name or not isinstance(pipeline, list):
            raise HTTPException(
                400, f"Geçersiz mongo_aggregate argümanları: {step['arguments']}"
            )

        # Agent e-mail'de geniş regex koruması
        if any(
            "$match" in st and "calls.agent_email" in st["$match"]
            and isinstance(st["$match"]["calls.agent_email"], dict)
            and "$regex" in st["$match"]["calls.agent_email"] for st in pipeline
        ):
            return {"message": "Agent e-mail için regex içeren sorgular desteklenmiyor."}, None, []

        docs = list(db[coll_name].aggregate(pipeline))
        last_docs = docs

        if not docs:
            return {"message": "Girilen kriterlere uygun kayıt bulunamadı."}, None, []

        # 1· lookup → 2· senkron clean → 3· enqueue eksikler
        need_lookup = [d for d in docs if "call_id" in d and not d.get("cleaned_transcript")] if call_level else []
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

        to_clean = [d for d in docs if d.get("transcript") and not d.get("cleaned_transcript")] if call_level else []
        for rec in to_clean:
            try:
                rec["cleaned_transcript"] = clean_transcript_sync(rec["call_id"])
                log.info("call_id %s senkron temizlendi.", rec["call_id"])
            except Exception as e:
                log.warning("call_id %s temizlenemedi: %s", rec["call_id"], e)

        needs_audio_tools = {"enqueue_transcription_job", "get_transcripts_by_customer_num",
               "get_transcript_by_call_id", "get_random_transcripts",
               "call_insights", "mini_rag"}

        def project_wants_text(ppl):
            for st in ppl:
                if "$project" in st:
                    keys = st["$project"].keys()
                    if ("transcript" in keys ) or ("cleaned_transcript" in keys):
                        return True
            return False
        
        tools_demand_text = bool(needs_audio_tools & requested_tools)
        pipeline_wants_text = project_wants_text(pipeline)

        missing_call_ids = [d["call_id"] for d in docs if "call_id" in d and not d.get("cleaned_transcript")] if call_level else []
        last_missing_call_ids = missing_call_ids

        if call_level and missing_call_ids and (tools_demand_text or pipeline_wants_text):
            qinfo = queue_utils.enqueue_downloads(missing_call_ids)
            for d in docs:
                cid = d["call_id"]
                if cid in qinfo["new_items"]:
                    d["message"] = "Transcript hazır değil. Kuyruğa alındı."
                elif cid in qinfo["already_items"]:
                    pos = qinfo["positions"].get(cid)
                    if pos:
                        d["message"] = f"Transcript hazır değil • **zaten sırada** (#{pos})"
                    else:
                        d["message"] = "Transcript hazır değil • **işleniyor**"

        collected_results.append({"name": "mongo_aggregate", "output": bson_safe(docs)})

    if collected_results:
        return {"results": collected_results}, last_docs, last_missing_call_ids

    return None, last_docs, last_missing_call_ids


