# handlers/mini_rag_sync_handler.py

from shared_lib.notification_utils import create_notification, get_user_and_session_by_chat_message_id
import logging

def get_logger():
    return logging.getLogger("executor_api")

def sync_mini_rag_summary_handler(
    audio_coll, 
    queue_utils, 
    clean_transcript_sync, 
    generate_mini_rag_output, 
    step_args
):
    log = get_logger()
    cnum = step_args["customer_num"]
    notification_id = step_args.get("notification_id")
    doc = audio_coll.find_one({"customer_num": cnum})
    if not doc:
        return {"name": "get_mini_rag_summary", "output": {"message": f"{cnum} için kayıt yok"}}
    log.info("miniRAG %s için özet senkron üretimi", cnum)

    # Özet zaten varsa direkt dön
    if doc.get("mini_rag", {}).get("summary"):
        return {"name": "get_mini_rag_summary", "output": doc["mini_rag"]}

    # Eksik cleaned varsa sync temizle
    for c in doc["calls"]:
        if not c.get("cleaned_transcript") and c.get("transcript"):
            try:
                clean_transcript_sync(c["call_id"])
            except Exception as e:
                log.warning("clean fail %s: %s", c["call_id"], e)

    # Temizlik sonrası özet üretilebilir mi?
    calls_doc = audio_coll.find_one(
        {"customer_num": cnum},
        {"calls.call_id": 1, "calls.cleaned_transcript": 1}
    )["calls"]

    missing_callids = [c["call_id"] for c in calls_doc if not c.get("cleaned_transcript")]


    # Sadece eksik varsa notification açıyoruz!
    if missing_callids:
        dl_info = queue_utils.enqueue_downloads(missing_callids, notification_id=notification_id,mongo=audio_coll.database)
        log.info("Eksik %s çağrı download kuyruğuna alındı: %s", cnum, dl_info)

    # Her durumda mini_rag kuyruğuna notification_id ile ekle (None olabilir, sorun değil)
    q = queue_utils.enqueue_mini_rag(cnum, notification_id=notification_id,mongo=audio_coll.database)

    if q["already_enqueued"]:
       msg = (
            f"{cnum} için işlem zaten kuyruğa alınmış. "
            f"Şu anki sıranız: {q['position']}/{q['total_pending']}. "
            f"İşlem tamamlandığında bildirim alacaksınız."
        )
    else:
        msg = (
            f"Analiz kuyruğa alındı. Şu anki sıranız: {q['position']}/{q['total_pending']}. "
            f"İşlem tamamlandığında bildirim alacaksınız."
        )
    return {"name": "get_mini_rag_summary", "output": {"message": msg}}
