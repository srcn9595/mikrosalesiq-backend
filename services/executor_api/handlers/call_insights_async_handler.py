# handlers/call_insights_async_handler.py

def call_insights_async_handler(db, queue_utils, docs):
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
    return None
