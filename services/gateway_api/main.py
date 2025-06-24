from fastapi import FastAPI, Request, HTTPException
import httpx, os, urllib.parse as up
from typing import Any, Dict
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging
import pathlib, json
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from shared_lib.mongo_chat_utils import insert_message, create_chat_session_if_needed
from shared_lib.jwt_utils import verify_token

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

ROOT_DIR   = pathlib.Path(__file__).parent
CONFIG_DIR = ROOT_DIR / "config"

if not CONFIG_DIR.exists():          # kökteki /app/config var mı?
    CONFIG_DIR = pathlib.Path(__file__).resolve().parent / "config"

with open(CONFIG_DIR / "allowed_tools.json", encoding="utf-8") as f:
    ALLOWED_TOOLS = set(json.load(f))

@app.post("/api/analyze")
async def analyze(request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Yetkisiz erişim.")
    user_info = verify_token(auth)
    payload = await request.json()
    query = payload.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(400, "Geçersiz query parametresi.")
    
    # 0️⃣ Yeni session başlat ve ilk mesajı kaydet
    user_id = user_info.get("sub") or "unknown"
    username = user_info.get("preferred_username", "")
    email = user_info.get("email", "")
    session_id = payload.get("session_id")

    session_id = create_chat_session_if_needed(user_id, session_id)

    insert_message(session_id, "user", {"type":"text", "content": query},user_id=user_id,username=username,email=email)

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
            insert_message(session_id, "bot", {"type":"text","content":"Ben, MikroSalesIQ satış zekası sisteminin bir parçasıyım.\n"
                    "Mikro grup tarafından geliştirildim ve yapay zeka destekli çağrı analizi yaparak\n"
                    "müşteri temsilcilerine ve yöneticilere akıllı satış öngörüleri sunarım.\n"
                    "Altyapımda OpenAI, FastAPI, MongoDB, Redis, Pinecone gibi teknolojiler kullanılmaktadır."})
            return {
                "type": "text",
                "content": (
                    "Ben, MikroSalesIQ satış zekası sisteminin bir parçasıyım.\n"
                    "Mikro grup tarafından geliştirildim ve yapay zeka destekli çağrı analizi yaparak\n"
                    "müşteri temsilcilerine ve yöneticilere akıllı satış öngörüleri sunarım.\n"
                    "Altyapımda OpenAI, FastAPI, MongoDB, Redis, Pinecone gibi teknolojiler kullanılmaktadır."
                ),
                "session_id": session_id
            }

        # 4️⃣ Desteklenmeyen plan → fail
        if not any(step.get("name") in ALLOWED_TOOLS for step in plan):
            err = "Üzgünüz, isteğiniz işlenemedi. Lütfen parametrelerinizi kontrol ederek tekrar deneyin veya destek ekibine başvurun."
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "failed",
                    "error": err,
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )
            insert_message(session_id, "bot", {"type": "text", "content": err})
            return {"type": "text", "content": err,"session_id": session_id}

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
            insert_message(session_id, "bot", {"type": "text", "content": "İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin."})
            return {
                "type": "text",
                "content": "İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin.",
                "session_id": session_id
            }

        # 6️⃣ Executor yanıtını al, NoneType’e karşı koru
        executor_json = exec_resp.json() or {}
        if not isinstance(executor_json, dict):
            raise HTTPException(500, "Beklenmeyen formatta yanıt alındı.")
        logging.info(f"Executor yanıtı: {executor_json}")

       # 7️⃣ get_mini_rag_summary varsa: özet(ler)i işle
        if any(s["name"] == "get_mini_rag_summary" for s in plan):

            # 7-a) Kuyruğa alındı mesajı geldiyse
            if "message" in executor_json:
                msg = executor_json["message"]
                await mongo.analysis_workflows.update_one(
                    {"_id": wf_id},
                    {"$set": {
                        "status": "succeeded",
                        "results": [{"name": "get_mini_rag_summary",
                                     "output": {"message": msg}}],
                        "timestamps.completed_at": datetime.utcnow()
                    }}
                )
                insert_message(session_id, "bot", {"type": "text", "content": msg})
                return {"type": "text", "content": msg, "session_id": session_id}

            # 7-b) Bir veya birden çok summary döndü
            summaries = [
                step["output"]
                for step in executor_json.get("results", [])
                if step.get("name") == "get_mini_rag_summary"
            ]

            if not summaries:          # emniyet
                raise HTTPException(500, "Özet beklenirken sonuç alınamadı.")

            # Mongo’ya tüm özetleri kaydet
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                    "status": "succeeded",
                    "results": [
                        {"name": "get_mini_rag_summary", "output": o}
                        for o in summaries
                    ],
                    "timestamps.completed_at": datetime.utcnow()
                }}
            )

            # Frontend’e her özet için bir “item” döndür
            items = [
                {
                    "customer_profile": o.get("customer_profile", {}),
                    "summary":          o.get("summary", ""),
                    "recommendations":  o.get("recommendations", []),
                    "sales_scores":     o.get("sales_scores", {}),
                    "merged_transcript":o.get("merged_transcript", "")
                }
                for o in summaries
            ]
            insert_message(session_id, "bot", {"type": "json", "content": {"items": items}})
            return {"type": "json", "content": {"items": items}, "session_id": session_id}

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
            insert_message(session_id, "bot", {"type": "text", "content": message})
            return {"type":"text", "content": message,session_id: session_id}

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
            insert_message(session_id, "bot", {"type": "text", "content": msg})
            return {"type":"text", "content": msg, "session_id": session_id}

        # 🔟 mongo_aggregate sonuçlarını parse et ve dök
        all_items: list[dict] = []

        for step in executor_json.get("results", []):
            if step.get("name") != "mongo_aggregate":
             continue

            raw = step.get("output", []) or []
            BLACKLIST = {
                 "_id", "file_path", "raw_transcript", "downloaded_at",
                 "transcribed_at", "cleaned_at", "call_key", "token_count"
             }

            for rec in raw:
                # İstenmeyen alanları at
                clean = {k: v for k, v in rec.items() if k not in BLACKLIST}

                # call_id garantiye al
                if "call_id" not in clean and rec.get("call_id"):
                    clean["call_id"] = rec["call_id"]

                # mesaj varsa koru
                if "message" in rec:
                    clean["message"] = rec["message"]

                all_items.append(clean)

        # En az bir mongo_aggregate sonucu varsa kaydet + dön
        if all_items:
            await mongo.analysis_workflows.update_one(
                {"_id": wf_id},
                {"$set": {
                     "status": "succeeded",
                     "results": [{"name": "mongo_aggregate", "output": all_items}],
                     "timestamps.completed_at": datetime.utcnow()
              }}
            )
            insert_message(session_id, "bot", {"type": "json", "content": {"items": all_items}})
            return {"type": "json", "content": {"items": all_items}, "session_id": session_id}

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
                insert_message(session_id, "bot", {"type": "json", "content": out})
                return {"type":"json", "content": out, "session_id": session_id}
            
        # 1️⃣2️⃣ get_call_metrics varsa
        for step in executor_json.get("results", []):
            if step.get("name") == "get_call_metrics":
                out = step.get("output", {})
                await mongo.analysis_workflows.update_one(
                    {"_id": wf_id},
                    {"$set": {
                        "status": "succeeded",
                        "results": [{"name": "get_call_metrics", "output": out}],
                        "timestamps.completed_at": datetime.utcnow()
                    }}
                )
                insert_message(session_id, "bot", {"type": "json", "content": out})
                return {"type": "json", "content": out, "session_id": session_id}



        # 🔺 Hiçbiri çalışmadıysa hata
        await mongo.analysis_workflows.update_one(
            {"_id": wf_id},
            {"$set": {
                "status": "failed",
                "error": "Beklenmeyen executor sonucu",
                "timestamps.completed_at": datetime.utcnow()
            }}
        )
        insert_message(session_id, "bot", {"type": "text", "content": "İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin."})
        return {
            "type":"text",
            "content":"İşleminiz sırasında bir aksaklık yaşandı. Lütfen birkaç dakika sonra tekrar deneyin.",
            "session_id": session_id
        }