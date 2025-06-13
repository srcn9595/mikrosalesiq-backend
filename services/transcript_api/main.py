from fastapi import FastAPI, Request, HTTPException
from pymongo import MongoClient
from fastapi.responses import JSONResponse
import os
app = FastAPI()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "mikrosalesiq")
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
audio_jobs_collection = db["audio_jobs"]
@app.post("/transcript")
async def get_transcript(request: Request):
    print("Aşama 1: request alındı", flush=True)
    body = await request.json()
    filters = body.get("filters", {})
    call_id = (filters.get("call_id") or "").strip()

    if not call_id:
        raise HTTPException(status_code=400, detail="call_id is required for this request.")
    
    job = audio_jobs_collection.find_one({
        "calls.call_id": call_id
    })
   
    if not job:
        return {
            "status": "not_found",
            "message": f"No transcript found for call_id {call_id}."
        }
    
    matched_call = next((c for c in job["calls"] if c["call_id"] == call_id), None)
    if not matched_call:
        return {
            "status": "not_found",
            "message": f"No transcript found for call_id {call_id}."
        }
    
    transcript = matched_call.get("cleaned_transcript")
    if not transcript:
        return {
            "status": "empty",
            "message": f"No cleaned_transcript found for call_id {call_id}.",
            "call_id": call_id,
            }
    return {
        "status": "success",
        "call_id": call_id,
        "transcript": transcript,
        "metadata": {
            "customer_num": job.get("customer_num"),
            "agent_email": matched_call.get("agent_email"),
            "call_date": matched_call.get("call_date"),
        }
    }
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print("GLOBAL ERROR:", exc)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": f"Beklenmedik bir hata oluştu: {str(exc)}"
        }
    )
