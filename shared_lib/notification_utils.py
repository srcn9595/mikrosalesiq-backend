from datetime import datetime
from bson import ObjectId

def create_notification(
    mongo,
    *,
    user_id,
    session_id,
    notif_type,
    related_customers,
    request_context=None,
    queue_key=None,
    title=None,
    message=None,
    auto_hide=False,
    popup_shown=False
):
    """
    Kapsamlı ve production-ready notification oluşturur.
    """
    now = datetime.utcnow()
    notif = {
        "user_id": user_id,
        "session_id": session_id,
        "type": notif_type,  # "mini_rag" vs.
        "related_customer": related_customers[0] if related_customers and len(related_customers) == 1 else None,
        "related_customers": related_customers or [],
        "status": "pending",       # "pending", "processing", "done", "failed"
        "seen": False,
        "dismissed": False,
        "title": title or "İşleminiz kuyruğa alındı",
        "message": message or "",
        "request_context": request_context or {},
        "queue_key": queue_key,
        "auto_hide": auto_hide,
        "popup_shown": popup_shown,
        "created_at": now,
        "completed_at": None,
        "result": None,
        "error": None,
        # Ek alanlar eklenebilir!
    }
    res = mongo.notifications.insert_one(notif)
    return str(res.inserted_id)

def update_notification_status(mongo, notification_id, **kwargs):
    """
    Notification'ı güncellerken eksik alan bırakma!
    """
    kwargs["updated_at"] = datetime.utcnow()
    # Eğer "status" done/failed ise completed_at setle
    if "status" in kwargs and kwargs["status"] in ("done", "failed"):
        kwargs.setdefault("completed_at", datetime.utcnow())
    mongo.notifications.update_one(
        {"_id": ObjectId(notification_id)},
        {"$set": kwargs}
    )
