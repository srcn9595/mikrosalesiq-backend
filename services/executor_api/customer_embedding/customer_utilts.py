import os
import logging
import tiktoken
from openai import OpenAI, OpenAIError, APIConnectionError, APITimeoutError
from typing import List, Optional
from pathlib import Path
import backoff

log = logging.getLogger("customer_utils")

OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL       = os.getenv("CUSTOMER_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("CUSTOMER_TEMP", "0.3"))
MAX_CHUNK_TOKENS   = int(os.getenv("CUSTOMER_MAX_TOKENS", "12000"))

SYSTEM_PROMPT_PATH = Path(__file__).parent / "config" / "customer_prompt.txt"

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY tanımlı değil.")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
enc = tiktoken.encoding_for_model(OPENAI_MODEL)

def num_tokens(text: str) -> int:
    return len(enc.encode(text))

def extract_json(response_text: str) -> str:
    start = response_text.find("{")
    end   = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return response_text[start:end+1]
    raise ValueError("Yanıt içinde geçerli JSON bulunamadı.")

@backoff.on_exception(backoff.expo, (OpenAIError, TimeoutError, APIConnectionError, APITimeoutError), max_tries=4)
def generate_general_insight_from_customers(docs: List[dict], query: Optional[str] = None) -> dict:
    if not docs:
        return {"message": "⚠️ Analiz için müşteri verisi yok."}

    summaries = []
    for doc in docs:
        acc = doc.get("account_name", "Bilinmeyen Müşteri")
        prof = doc.get("customer_profile", {})
        summ = doc.get("mini_rag", {}).get("summary", "")
        recs = doc.get("recommendations", [])
        risk = doc.get("risk_score", None)

        parts = [f"🧾 {acc}"]

        if prof:
            parts.append(f"📋 Profil: {prof}")
        if risk is not None:
            parts.append(f"⚠️ Risk Skoru: {risk}")
        if summ:
            parts.append(f"📄 Özet: {summ}")
        if recs:
            parts.append(f"💡 Öneriler: {recs}")

        summaries.append("\n".join(parts))

    full_text = "\n\n---\n\n".join(summaries)

    if num_tokens(full_text) > MAX_CHUNK_TOKENS:
        log.warning("⚠️ Toplam token sayısı limitin üstünde, ilk 10 müşteriyle sınırlandırılıyor.")
        full_text = "\n\n---\n\n".join(summaries[:10])

    prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    try:
        user_query_text = f"Aşağıdaki {len(docs)} müşteriye ait satış analizlerini incele."
        if query:
            user_query_text += f" Soru: {query}"

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{user_query_text}\n\n{full_text}"}
            ]
        )
        raw_output = response.choices[0].message.content.strip()
        return extract_json(raw_output)

    except Exception as e:
        log.exception("❌ LLM genel analiz hatası:")
        return {"message": f"❌ LLM hata: {e}"}
