import os
import logging
import tiktoken
from typing import List
from openai import OpenAI, OpenAIError, APIConnectionError, APITimeoutError
import backoff
from pathlib import Path

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
def generate_cleaned_transcript_sync(call_id: str, transcript: str, call_date: str) -> str:
    """
    Bu fonksiyon, ham transkripti OpenAI'ye göndererek temizlenmiş (düzenlenmiş) halini döner.
    Artık müşteri numarası veya e-posta içermez.
    """

    # Sistem mesajı: model davranışını yönlendirir
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # Kullanıcıya özel bağlamsal mesaj (isteğe bağlı)
    context_info = f"Çağrı Kimliği: {call_id}\nÇağrı Tarihi: {call_date}"

    full_prompt = f"{context_info}\n\n{transcript}"

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=OPENAI_TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": full_prompt}
        ]
    )

    return response.choices[0].message.content.strip()
