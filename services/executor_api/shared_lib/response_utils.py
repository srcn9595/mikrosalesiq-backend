from fastapi.responses import JSONResponse
from typing import Any, Dict, List

def format_gateway_response(executor_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executor’dan gelen raw JSON’u alıp tam Gateway /api/analyze
    handler’ındaki `return {"type":…, "content":…}` bloklarına 
    denk gelecek şekilde dönüştürüyor.
    """

    # 7️⃣ get_mini_rag_summary varsa
    if any(s["name"] == "get_mini_rag_summary" for s in executor_json.get("plan", [])):
        # 7-a) Kuyruğa alındı mesajı
        if "message" in executor_json:
            return {"type": "text", "content": executor_json["message"]}

        # 7-b) summary listesi
        summaries = [
            step["output"]
            for step in executor_json.get("results", [])
            if step.get("name") == "get_mini_rag_summary"
        ]
        if summaries:
            # frontend’in beklediği json yapısı:
            items = [
                {
                    "customer_profile": o.get("customer_profile", {}),
                    "summary":           o.get("summary", ""),
                    "recommendations":   o.get("recommendations", []),
                    "audio_analysis":    o.get("audio_analysis", {}),
                    "sales_scores":      o.get("sales_scores", {}),
                    "merged_transcript": o.get("merged_transcript", ""),
                    "next_steps":        o.get("next_steps", []),
                    "conversion_probability": o.get("conversion_probability"),
                    "risk_score":            o.get("risk_score"),
                }
                for o in summaries
            ]
            return {"type": "json", "content": {"items": items}}

    # 8️⃣ enqueue_mini_rag adımıysa
    if "message" in executor_json and executor_json.get("results", []) and any(
        step["name"] == "enqueue_mini_rag" for step in executor_json["results"]
    ):
        return {"type": "text", "content": executor_json["message"]}

    # 9️⃣ Genel "message"
    if "message" in executor_json:
        return {"type": "text", "content": executor_json["message"]}

    # 🔟 mongo_aggregate
    for step in executor_json.get("results", []):
        if step.get("name") == "mongo_aggregate":
            raw = step.get("output", [])
            # frontend’in beklediği forma dönüştürün…
            # (işinize göre temizleme vs. ekleyin)
            return {"type": "json", "content": {"items": raw}}

    # fallback
    return {"type": "text", "content": "Beklenmeyen executor sonucu."}