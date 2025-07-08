from datetime import datetime
from bson import ObjectId,json_util
import _asyncio
import os
import httpx

from shared_lib.response_utils import format_gateway_response
from notification_fcm import notify_user_fcm
from shared_lib.async_tools import ASYNC_TOOLS


COMPLETE_STATUSES = {"done", "failed", "error"}

def create_notification(
    mongo,
    *,
    user_id = None,
    session_id = None,
    notif_type,
    related_customers=None,
    chat_message_id=None,
    jobs=None,  # [{"customer_num": ..., "call_ids": [...], "status": "pending"}]
    request_context=None,
    queue_key=None,
    title=None,
    message=None,
    auto_hide=False,
    popup_shown=False,
    is_async_process=None,
    status=None,
    plan=None
):
    now = datetime.utcnow()
    notif = {
        "user_id": user_id,
        "session_id": session_id,
        "type": notif_type,
        "related_customers": related_customers or [],
        "related_customer": related_customers[0] if related_customers and len(related_customers) == 1 else None,
        "chat_message_id": chat_message_id,
        "jobs": jobs or [],
        "status": status or ("pending" if is_async_process else "instant"),
        "is_async_process": is_async_process,
        "plan": plan,
        "seen": False,
        "dismissed": False,
        "title": title or "İşleminiz kuyruğa alındı",
        "message": message or "",
        "request_context": request_context or {},
        "queue_key": queue_key,
        "auto_hide": auto_hide,
        "popup_shown": popup_shown,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    res = mongo.notifications.insert_one(notif)
    return str(res.inserted_id)

def create_notification_job(
    mongo,
    job_type,
    notification_id,
    customer_num,
    status="pending",
    call_ids=None,
    result=None,
    error=None,
):
    """
    Sadece job context'iyle yeni bir notification jobs[] girişi ekler veya günceller.
    """
    job = {
        "customer_num": customer_num,
        "type": job_type,
        "call_ids": call_ids or [],
        "status": status,
        "result": result,
        "error": error,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    # Gerekirse notification'a jobs[] push et
    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$push": {"jobs": job}}
    )
    return job  # job objesini döner, id yok (listede index'i bulabilirsin)

def update_notification_status(
    mongo,
    notification_id,
    *,
    status=None,
    jobs=None,
    message=None,
    result=None,
    error=None,
):
    update = {"updated_at": datetime.utcnow()}
    if status:
        update["status"] = status
        if status in ("done", "failed"):
            update["completed_at"] = datetime.utcnow()
    if jobs is not None:
        update["jobs"] = jobs
    if message is not None:
        update["message"] = message
    if result is not None:
        update["result"] = result
    if error is not None:
        update["error"] = error

    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": update}
    )

def update_job_in_notification(
    mongo,
    notification_id,
    customer_num,
    call_id=None,
    job_status=None,
    result=None,
    error=None,
):
    notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
    if not notif:
        return False

    jobs = notif.get("jobs", [])
    updated = False

    for job in jobs:
        if job.get("customer_num") == customer_num:
            if call_id and "call_ids" in job and job["call_ids"]:
                if call_id in job["call_ids"]:
                    job["status"] = job_status or job["status"]
                    if result: job["result"] = result
                    if error: job["error"] = error
                    updated = True
            else:
                job["status"] = job_status or job["status"]
                if result: job["result"] = result
                if error: job["error"] = error
                updated = True

    all_done = all(j.get("status") == "done" for j in jobs if j.get("status") not in ("failed", "error"))
    notif_status = "done" if all_done else "pending"

    update = {
        "jobs": jobs,
        "status": notif_status,
        "updated_at": datetime.utcnow(),
    }
    if notif_status == "done":
        update["completed_at"] = datetime.utcnow()

    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": update}
    )
    return updated

def mark_notification_seen(mongo, notification_id):
    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": {"seen": True, "updated_at": datetime.utcnow()}}
    )

def mark_notification_dismissed(mongo, notification_id):
    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": {"dismissed": True, "updated_at": datetime.utcnow()}}
    )

def get_user_notifications(mongo, user_id, only_unseen=False, limit=25):
    query = {"user_id": user_id}
    if only_unseen:
        query["seen"] = False
    return list(
        mongo.notifications.find(query).sort("created_at", -1).limit(limit)
    )

def get_user_and_session_by_chat_message_id(mongo, chat_message_id):
    msg = mongo.chat_messages.find_one({"_id": ObjectId(chat_message_id)})
    if not msg:
        return None, None
    return msg.get("user_id"), msg.get("session_id")

def get_notification_by_id(mongo, notification_id):
    return mongo.notifications.find_one({"_id": ObjectId(notification_id)})

def get_notification_id_for_call(mongo, call_id):
    notif = mongo.notifications.find_one({
        "jobs.call_ids": call_id,
        "status": {"$in": ["pending", "processing","done"]}
    })
    return str(notif["_id"]) if notif else None

from bson import ObjectId

def update_notification_with_user_and_session(mongo, notification_id: str) -> bool:
    # Notification'ı al
    notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
    if not notif:
        print(f"Notification {notification_id} bulunamadı.")
        return False

    chat_message_id = notif.get("chat_message_id")
    if not chat_message_id:
        print(f"Notification {notification_id} için chat_message_id bulunamadı.")
        return False

    # Chat message'ı al
    chat_message = mongo.chat_messages.find_one({"_id": ObjectId(chat_message_id)})
    if not chat_message:
        print(f"Chat message {chat_message_id} bulunamadı.")
        return False

    # User ID ve Session ID'yi al
    user_id = chat_message.get("user_id")
    session_id = chat_message.get("session_id")
    fcm_token = chat_message.get("fcm_token")  # FCM token'ı alıyoruz
    
    # Chat mesajının content kısmını al
    content = chat_message.get("content")
    if not content:
        print(f"Chat message {chat_message_id} için content bulunamadı.")
        return False

    # Notification'ı güncelle
    if user_id and session_id and fcm_token:  # Artık fcm_token da var
        mongo.notifications.update_one(
            {"_id": ObjectId(notification_id)},
            {"$set": {
                "user_id": user_id,
                "session_id": session_id,
                "title": content,  # Chat message content'i title olarak güncelleniyor
                "fcm_token": fcm_token  # FCM token'ı da ekliyoruz
            }}
        )
        # Güncellenmiş Notification objesini geri döndür
        updated_notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
        print(f"Notification {notification_id} güncellendi: user_id, session_id, title ve fcm_token set edildi.")
        return updated_notif  # Güncellenmiş objeyi döndür
    else:
        print(f"Chat message {chat_message_id} için user_id, session_id veya fcm_token eksik.")
        return False


def finalize_notification_if_ready(mongo, notification_id: str) -> bool:
    import logging
    log = logging.getLogger("notification_finalize")
    notif = mongo.notifications.find_one({"_id": ObjectId(notification_id)})
    log.info(f"[{notification_id}] finalize_notification_if_ready: notif: {notif is not None}, plan: {bool(notif and notif.get('plan'))}")

    if not notif or not notif.get("plan"):
        log.warning(f"[{notification_id}] Notification veya plan yok, çıkılıyor.")
        return False

    plan = notif["plan"]
    required_types = set()
    for step in plan:
        name = step.get("name")
        if name in ASYNC_TOOLS:
            required_types.add(ASYNC_TOOLS[name])
    log.info(f"[{notification_id}] required_types: {required_types}")

    if not required_types:
        log.info(f"[{notification_id}] Hiçbir required_type yok, çıkılıyor.")
        return False

    jobs = notif.get("jobs", [])
    type_status = {t: False for t in required_types}
    for job in jobs:
        t = job.get("type")
        if t in required_types and job.get("status") == "done":
            type_status[t] = True
    log.info(f"[{notification_id}] job status: {type_status}")

    if not all(type_status.values()):
        log.info(f"[{notification_id}] Hala tamamlanmamış job var, çıkılıyor.")
        return False

    # 3️⃣ Eğer mini_rag varsa summary Mongo’da gerçekten var mı? 
    if "mini_rag" in required_types:
        cnums = [job.get("customer_num") for job in jobs if job.get("type") == "mini_rag"]
        audio_coll = mongo["audio_jobs"]
        for cnum in cnums:
            doc = audio_coll.find_one({"customer_num": cnum})
            log.info(f"[{notification_id}] mini_rag customer_num={cnum}, doc_mini_rag_exists={bool(doc and doc.get('mini_rag', {}).get('summary'))}")
            if not doc or not doc.get("mini_rag", {}).get("summary"):
                log.info(f"[{notification_id}] mini_rag summary yok, çıkılıyor.")
                return False

    # 4️⃣ Artık her şey hazır, gateway'e git
    log.info(f"[{notification_id}] Tüm koşullar tamam, gateway'e post atılıyor. Plan: {plan}")
    executor_base = os.getenv("EXECUTOR_API_URL", "http://executor_api:8000")
    executor_url  = f"{executor_base}/execute"
    
    try:
        if notif.get("user_id") is None or notif.get("session_id") is None:
            notif= update_notification_with_user_and_session(mongo, notification_id)

        # Executor'a istek gönderir
        resp = httpx.post(executor_url, json=plan, timeout=30)
        resp.raise_for_status()
        executor_json = resp.json()

        executor_json["plan"] = plan
        formatted = format_gateway_response(executor_json)

        mongo.notifications.update_one(
            {"_id": ObjectId(notification_id)},
            {"$set": {
                "status":       "done",
                "completed_at": datetime.utcnow(),
                "result":       formatted
            }}
        )
        log.info(f"[{notification_id}] Notification güncellendi ve finalize edildi.")

        if notif.get("fcm_token"):
            extra_data = {
                "session_id": notif.get("session_id"),
                "title":notif.get("title"),
            }
           # notify_user_fcm(fcm_token=notif["fcm_token"], title=notif["title"], body=notif["title"], data=extra_data)
        return True

    except httpx.RequestError as e:
        log.error(f"[{notification_id}] Gateway'e istek gönderilemedi: {e}")
        return False





