from fastapi import FastAPI, Request, HTTPException
import httpx, os, urllib.parse as up
from typing import Any, Dict
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging
def ensure_path(url: str, suffix: str) -> str:
    parts = up.urlparse(url)
    return url.rstrip("/") + suffix if not parts.path.strip("/") else url.rstrip("/")

INTENT_API_URL = ensure_path(
    os.getenv("INTENT_API_URL", "http://intent_api:8000"),
    "/analyze"
)
EXECUTOR_API_URL = ensure_path(
    os.getenv("EXECUTOR_API_URL", "http://executor_api:8000"),
    "/execute"
)

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB", "miksalesiq")
mongo     = AsyncIOMotorClient(MONGO_URI)[MONGO_DB]

TIMEOUT = httpx.Timeout(30.0, read=30.0)
app = FastAPI()


@app.post("/api/analyze")
async def analyze(request: Request):
    payload = await request.json()
    query = payload.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(400, "Geçersiz query parametresi.")

    # 1️⃣ Workflow kaydı oluştur
    workflow = {
        "query": query,
        "plan": None,
        "status": "planned",
        "results": None,
        "error": None,
        "timestamps": {"planned_at": datetime.utcnow()}
    }
    wf_res = await mongo.analysis_workflows.insert_one(workflow)
    wf_id  = wf_res.inserted_id

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 2️⃣ Intent API’den plan al
        intent_resp = await client.post(INTENT_API_URL, json={"query": query})
        intent_resp.raise_for_status()
        intent_json = intent_resp.json()
        plan = intent_json.get("plan", [])
        await mongo.analysis_workflows.update_one(
            {"_id": wf_id},
            {"$set": {"plan": plan}}
        )

        # 3️⃣ meta_about_creator special case
        if any(step.get("name") == "meta_about_creator" for step in plan):
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "succeeded",
                    "results": [{"name": "meta_about_creator"}],
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            return {
                "type": "text",
                "content": (
                    "Ben, MikroSalesIQ satış zekası sisteminin bir parçasıyım.\n"
                    "Sercan Işık tarafından geliştirildim ve yapay zeka destekli çağrı analizi yaparak\n"
                    "müşteri temsilcilerine ve yöneticilere akıllı satış öngörüleri sunarım.\n"
                    "Altyapımda OpenAI, FastAPI, MongoDB, Redis, Pinecone gibi teknolojiler kullanılmaktadır."
                )
            }

        # 4️⃣ Desteklenmeyen plan → fail
        if not any(step.get("name") in ("mongo_aggregate","enqueue_mini_rag","get_mini_rag_summary","write_call_insights","call_insights")
                   for step in plan):
            err = "Üzgünüz, isteğiniz işlenemedi. Lütfen parametrelerinizi kontrol ederek tekrar deneyin veya destek ekibine başvurun."
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "failed",
                    "error": err,
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            return {"type": "text", "content": err}

        # 5️⃣ Executor’a gönder ve executing yap
        await mongo.analysis_workflows.update_one(
            {"_id": wf_id},
            {"$set": {
                "status": "executing",
                "timestamps.executed_at": datetime.utcnow()
            }}
        )
        exec_resp = await client.post(EXECUTOR_API_URL, json=plan)
        try:
            exec_resp.raise_for_status()
        except Exception:
            error_text = exec_resp.text
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "failed",
                    "error": error_text,
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            return {
                "type": "text",
                "content": "İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin."
            }

        # 6️⃣ Executor yanıtını al, NoneType’e karşı koru
        executor_json = exec_resp.json() or {}
        if not isinstance(executor_json, dict):
            raise HTTPException(500, "Beklenmeyen formatta yanıt alındı.")
        logging.info(f"Executor yanıtı: {executor_json}")
        # 7️⃣ get_mini_rag_summary adımı varsa önce onun sonucu
        # 7️⃣ get_mini_rag_summary adımı varsa önce onun sonucu
        if any(s["name"] == "get_mini_rag_summary" for s in plan):
            if "message" in executor_json:
                # Kuyruğa alma mesajı geldiğinde frontend'e bilgi ver
                msg = executor_json["message"]
                await mongo.analysis_workflows.update_one(
                    {"_id": wf_id},
                    {"$set": {
                        "status": "succeeded",
                        "results": [{"name": "get_mini_rag_summary", "output": {"message": msg}}],
                        "timestamps.completed_at": datetime.utcnow()
                    }}
                )
                return {"type": "text", "content": msg}

            # Normal summary yanıtı varsa işle
            results = executor_json.get("results", [])
            mini = next((r.get("output", {}) for r in results if r.get("name") == "get_mini_rag_summary"), {})

            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "succeeded",
                    "results": [{"name": "get_mini_rag_summary", "output": mini}],
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )

            return {
                "type": "json",
                "content": {
                    "items": [
                        {
                            "customer_profile": mini.get("customer_profile", {}),
                            "summary": mini.get("summary", ""),
                            "recommendations": mini.get("recommendations", []),
                            "sales_scores": mini.get("sales_scores", {}),
                            "merged_transcript": mini.get("merged_transcript", "")
                        }
                    ]
                }
            }


        # 8️⃣ enqueue_mini_rag adımıysa direkt mesaj dön
        if any(s["name"] == "enqueue_mini_rag" for s in plan):
            message = executor_json.get("message", "")
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "succeeded",
                    "results": [{"name":"enqueue_mini_rag","output":message}],
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            return {"type":"text", "content": message}

        # 9️⃣ Genel executor “message” varsa
        if "message" in executor_json:
            msg = executor_json["message"]
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "succeeded",
                    "results": [{"name":"message","output":msg}],
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            return {"type":"text", "content": msg}

        # 🔟 mongo_aggregate sonuçlarını parse et ve dök
        for step in executor_json.get("results", []):
            if step.get("name") == "mongo_aggregate":
                raw = step.get("output", [])
                if not raw:
                    await mongo.analysis_workflows.update_one(
                        {"_id": wf_id},
                        {"$set": {
                            "status": "succeeded",
                            "results": [{"name":"mongo_aggregate","output":[]}],
                            "timestamps.completed_at": datetime.utcnow()
                        }}
                    )
                    return {
                        "type":"text",
                        "content": "Aradığınız kriterlere uygun görüşme kaydı bulunamadı."
                    }

                items = []
                for rec in raw:
                    cid = rec.get("call_id")
                    # agent bilgisi
                    if rec.get("agent_email") or rec.get("agent_name"):
                        items.append({
                            "call_id": cid,
                            "agent_email": rec.get("agent_email",""),
                            "agent_name": rec.get("agent_name",""),
                            "call_date": rec.get("call_date",""),
                            "caller_id": rec.get("caller_id",""),
                            "called_num": rec.get("called_num","")
                        })
                    # transcript
                    elif rec.get("transcript") or rec.get("cleaned_transcript"):
                        txt = rec.get("transcript") or rec.get("cleaned_transcript")
                        items.append({
                            "call_id": cid,
                            "transcript": txt,
                            "call_date": rec.get("call_date","")
                        })
                    # sadece tarih
                    elif rec.get("call_date"):
                        items.append({
                            "call_id": cid,
                            "call_date": rec.get("call_date","")
                        })
                    # message
                    elif "message" in rec:
                        items.append({
                            "call_id": cid,
                            "message": rec["message"]
                        })
                    # fallback
                    else:
                        other = set(rec.keys()) - {"call_id"}
                        if not other:
                            items.append({"call_id": cid})
                        else:
                            items.append({
                                "call_id": cid,
                                "message": "Beklenmeyen bir sonuç yapısı var."
                            })

                await mongo.analysis_workflows.update_one(
                    {"_id": wf_id},
                    {"$set": {
                        "status": "succeeded",
                        "results": [{"name":"mongo_aggregate","output":items}],
                        "timestamps.completed_at": datetime.utcnow()
                    }}
                )
                return {"type":"json", "content": {"items": items}}

        # 1️⃣1️⃣ write_call_insights varsa
        for step in executor_json.get("results", []):
            if step.get("name") == "write_call_insights":
                out = step["output"]
                await mongo.analysis_workflows.update_one(
                    {"_id": wf_id},
                    {"$set": {
                        "status": "succeeded",
                        "results": [{"name":"write_call_insights","output":out}],
                        "timestamps.completed_at": datetime.utcnow()
                    }}
                )
                return {"type":"json", "content": out}

        # 🔺 Hiçbiri çalışmadıysa hata
        await mongo.analysis_workflows.update_one(
            {"_id": wf_id},
            {"$set": {
                "status": "failed",
                "error": "Beklenmeyen executor sonucu",
                "timestamps.completed_at": datetime.utcnow()
            }}
        )
        return {
            "type":"text",
            "content":"İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin."
        }