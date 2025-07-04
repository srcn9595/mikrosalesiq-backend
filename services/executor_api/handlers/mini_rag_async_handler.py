# handlers/mini_rag_async_handler.py

def mini_rag_async_handler(db, queue_utils, docs, notification_ids=None):
    """
    notification_ids: Dict[str, str] veya None
      Eğer None ise, her müşteri için notification_id=None gönderilir (default davranış)
      Eğer dict ise: customer_num -> notification_id şeklinde eşleşir
    """
    customer_nums = {d.get("customer_num") for d in docs if d.get("customer_num")}
    if not customer_nums:
        return None

    msgs = []
    for cnum in customer_nums:
        rec = db["audio_jobs"].find_one(
            {"customer_num": cnum}, {"mini_rag.summary": 1}
        )
        if rec and rec.get("mini_rag", {}).get("summary"):
            continue  # zaten var

        this_notification_id = None
        if notification_ids:
            if isinstance(notification_ids, dict):
                this_notification_id = notification_ids.get(cnum)
            else:
                this_notification_id = notification_ids

        qinfo = queue_utils.enqueue_mini_rag(
            cnum,
            notification_id=this_notification_id
        )
        status = "zaten sırada" if qinfo["already_enqueued"] else "kuyruğa eklendi"
        msgs.append(f"{cnum} {status} ({qinfo['position']}/{qinfo['total_pending']})")
    if msgs:
        return {
            "message": " | ".join(msgs)
        }
    return None
