import os
import pymongo
from datetime import datetime
from clean_transcript.clean_utils import generate_cleaned_transcript_sync, chunks_by_tokens

MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB   = os.getenv("MONGO_DB", "mikrosalesiq")
AUDIO_COLL = "audio_jobs"

client = pymongo.MongoClient(MONGO_URI)
db     = client[MONGO_DB]
audio  = db[AUDIO_COLL]

def clean_transcript_sync(call_id: str) -> str:
    doc = audio.find_one(
        {"calls.call_id": call_id},
        {"calls.$": 1, "customer_num": 1}
    )
    if not doc or not doc.get("calls"):
        raise ValueError(f"{call_id} için veri bulunamadı.")

    call = doc["calls"][0]
    transcript = call.get("transcript", "")
    if not transcript:
        raise ValueError(f"{call_id} için transcript boş.")
    
    call_date = call.get("call_date", "Tarih bilinmiyor")
    chunks = chunks_by_tokens(transcript, 8000)

    cleaned = "\n\n".join(
        generate_cleaned_transcript_sync(call_id, part, call_date)
        for part in chunks
    )

    audio.update_one(
        {"calls.call_id": call_id},
        {"$set": {
            "calls.$.cleaned_transcript": cleaned,
            "calls.$.status": "cleaned",
            "calls.$.cleaned_at": datetime.utcnow()
        }}
    )
    return cleaned

