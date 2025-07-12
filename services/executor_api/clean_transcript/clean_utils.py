import os
import logging
import tiktoken
from typing import List
from openai import OpenAI, OpenAIError, APIConnectionError, APITimeoutError
import backoff
from pathlib import Path
import re

log = logging.getLogger("clean_utils")

OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL       = os.getenv("CLEAN_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("CLEAN_TEMP", "0.3"))
MAX_CHUNK_TOKENS   = int(os.getenv("CLEAN_MAX_TOKENS", "12000"))

SYSTEM_PROMPT_PATH = Path(__file__).parent / "config" / "system_prompt.txt"

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY tanımlı değil.")

openai_client = OpenAI(api_key=OPENAI_API_KEY)
enc = tiktoken.encoding_for_model(OPENAI_MODEL)

def num_tokens(text: str) -> int:
    return len(enc.encode(text))

def is_audio_features_ready(af: dict) -> bool:
    if not af or not isinstance(af, dict):
        return False
    metrics = [
        af.get("agent_pitch_variance", 0),
        af.get("customer_pitch_variance", 0),
        af.get("speaking_rate_customer", 0),
        af.get("speaking_rate_agent", 0),
        af.get("agent_talk_ratio", 0),
        af.get("customer_filler_count", 0)
    ]
    return any(m > 0 for m in metrics)


def extract_json(response_text: str) -> str:
    start = response_text.find("{")
    end   = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return response_text[start:end+1]
    raise ValueError("Yanıt içinde geçerli JSON bulunamadı.")

def chunks_by_tokens(text: str, limit: int) -> List[str]:
    if num_tokens(text) <= limit:
        return [text]
    parts, buf = [], []
    for line in text.splitlines():
        buf.append(line)
        if num_tokens("\n".join(buf)) >= limit:
            parts.append("\n".join(buf[:-1]))
            buf = [line]
    if buf:
        parts.append("\n".join(buf))
    return parts

@backoff.on_exception(backoff.expo, (OpenAIError, TimeoutError, APIConnectionError, APITimeoutError), max_tries=4)
def generate_cleaned_transcript_sync(call_id: str, transcript: str, call_date: str, audio_features: dict = None) -> str:
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    context_info = f"Çağrı Kimliği: {call_id}\nÇağrı Tarihi: {call_date}"
    if audio_features and is_audio_features_ready(audio_features):
        context_info += "\n\nAşağıdaki ses analiz verilerini dikkate alarak yorum yap:\n"
        for k, v in audio_features.items():
            context_info += f"- {k.replace('_', ' ').capitalize()}: {v}\n"
    else:
        log.warning("⚠️ audio_features geçersiz ya da boş geldi, prompt'a eklenmeyecek.")

    full_prompt = f"{context_info}\n\n{transcript}"

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=OPENAI_TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": full_prompt}
        ]
    )

    raw_output = response.choices[0].message.content.strip()
    return extract_json(raw_output)
