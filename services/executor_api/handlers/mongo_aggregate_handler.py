from fastapi import HTTPException
from fastapi.responses import JSONResponse
from shared_lib.notification_utils import get_user_and_session_by_chat_message_id
import re
from datetime import datetime, timezone

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)

def convert_iso_dates(obj, use_utc=True):
    if isinstance(obj, dict):
        return {k: convert_iso_dates(v, use_utc) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_iso_dates(v, use_utc) for v in obj]
    if isinstance(obj, str) and _ISO_RE.match(obj):
        dt = datetime.fromisoformat(obj.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if use_utc else dt
    return obj

def mongo_aggregate_handler(
    db, audio_coll, queue_utils, clean_transcript_sync, plan, _fill_templates, _is_call_level, log, bson_safe, requested_tools
):
    collected_results: list = []
    context: dict = {}
    last_docs = None
    last_missing_call_ids = []

    def pipeline_needs_mini_rag(ppl):
        """Projeksiyon aşamasında gerçekten *istenen* (value != 0) bir
        `mini_rag*` veya `customer_profile*` alanı var mı?

        - `$project: {"mini_rag.summary": 1}`  → **True** (kuyruk gerek)
        - `$project: {"mini_rag": 0}`          → **False** (dışlama, kuyruk gerekmez)
        - `$project: {"lead_source": 1}`       → **False**
        """
        for st in ppl:
            proj = st.get("$project")
            if not proj:
                continue

            for key, val in proj.items():
                # 0 / False / None / ''  ➜  dışlama, yok say
                if not val:
                    continue
                if key.startswith("mini_rag") or key.startswith("customer_profile"):
                    return True
        return False

    for step in plan:
        if step.get("name") != "mongo_aggregate":
            continue

        step["arguments"] = _fill_templates(step["arguments"], context)
        coll_name = step["arguments"].get("collection")
        pipeline  = step["arguments"].get("pipeline")
        pipeline = convert_iso_dates(pipeline, use_utc=True)
        call_level = _is_call_level(pipeline)

        if not coll_name or not isinstance(pipeline, list):
            raise HTTPException(
                400, f"Geçersiz mongo_aggregate argümanları: {step['arguments']}"
            )

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

        project_keys = []
        for stage in pipeline:
            if "$project" in stage:
                project_keys = list(stage["$project"].keys())
                break

        if docs and project_keys:
            all_empty = all(
                all(doc.get(k) is None for k in project_keys if k != "_id") for doc in docs
            )
            if all_empty:
                return {"message": "Girilen kriterlere uygun kayıt bulunamadı."}, None, []

        need_lookup = [d for d in docs if "call_id" in d and not d.get("cleaned_transcript")] if call_level else []
        if need_lookup:
            ids = [d["call_id"] for d in need_lookup]
            cursor = audio_coll.aggregate([
                {"$unwind": "$calls"},
                {"$match": {"calls.call_id": {"$in": ids}}},
                {"$project": {
                    "_id": 0,
                    "call_id": "$calls.call_id",
                    "cleaned_transcript": "$calls.cleaned_transcript"
                }}
            ])
            lut = {c["call_id"]: c for c in cursor}
            for d in need_lookup:
                extra = lut.get(d["call_id"], {})
                d.setdefault("cleaned_transcript", extra.get("cleaned_transcript"))

        to_clean = [d for d in docs if d.get("transcript") and not d.get("cleaned_transcript")] if call_level else []
        for rec in to_clean:
            try:
                rec["cleaned_transcript"] = clean_transcript_sync(rec["call_id"])
                log.info("call_id %s senkron temizlendi.", rec["call_id"])
            except Exception as e:
                log.warning("call_id %s temizlenemedi: %s", rec["call_id"], e)

        needs_audio_tools = {
            "enqueue_transcription_job", "get_transcripts_by_customer_num",
            "get_transcript_by_call_id", "get_random_transcripts", "mini_rag"
        }

        def project_wants_text(ppl):
            for st in ppl:
                if "$project" in st:
                    keys = st["$project"].keys()
                    if "transcript" in keys or "cleaned_transcript" in keys:
                        return True
            return False

        tools_demand_text = bool(needs_audio_tools & requested_tools)
        pipeline_wants_text = project_wants_text(pipeline)

        missing_call_ids = [d["call_id"] for d in docs if "call_id" in d and not d.get("cleaned_transcript")] if call_level else []
        last_missing_call_ids = missing_call_ids

        if call_level and missing_call_ids and (tools_demand_text or pipeline_wants_text):
            notification_id = step["arguments"].get("notification_id")
            chat_message_id = step["arguments"].get("chat_message_id")

            if not notification_id and chat_message_id:
                notification_id, *_ = get_user_and_session_by_chat_message_id(db, chat_message_id)

            qinfo = queue_utils.enqueue_downloads(
                missing_call_ids,
                notification_id=notification_id,
                mongo=db
            )
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

            return {
                "message": "Analiz kuyruğa alındı, transcript işlemi tamamlandığında tekrar denenecek."
            }, None, missing_call_ids

        if not call_level and pipeline_needs_mini_rag(pipeline):
            customer_nums = list({d["customer_num"] for d in docs if "customer_num" in d})
            pending_mini_rag = []
            for cnum in customer_nums:
                doc = db["audio_jobs"].find_one(
                    {"customer_num": cnum},
                    {"mini_rag.summary": 1, "customer_profile": 1}
                )
                if not doc or not (doc.get("mini_rag", {}).get("summary") or doc.get("customer_profile")):
                    pending_mini_rag.append(cnum)

            if pending_mini_rag:
                notification_id = step["arguments"].get("notification_id")
                chat_message_id = step["arguments"].get("chat_message_id")

                if not notification_id and chat_message_id:
                    notification_id, *_ = get_user_and_session_by_chat_message_id(db, chat_message_id)

                for cnum in pending_mini_rag:
                    queue_utils.enqueue_mini_rag(
                        cnum,
                        notification_id=notification_id,
                        mongo=db
                    )

                return {
                    "message": f"{len(pending_mini_rag)} müşteri için analiz kuyruğa alındı, "
                               "işlem tamamlandığında bilgilendirileceksiniz."
                }, None, []

        collected_results.append({"name": "mongo_aggregate", "output": bson_safe(docs)})

    if collected_results:
        return {"results": collected_results}, last_docs, last_missing_call_ids

    return None, last_docs, last_missing_call_ids
