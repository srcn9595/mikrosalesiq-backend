import os
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any
from openai import OpenAI

log = logging.getLogger("mini_rag_utils")

ROOT = Path(__file__).parent / "mini_rag_config"
SYSTEM_PROMPT_PATH    = ROOT / "system_prompt.txt"
KNOWLEDGE_PROMPT_PATH = ROOT / "prompt_knowledge.md"
EXAMPLES_PROMPT_PATH  = ROOT / "prompt_examples.md"
_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\\.[^@]+$")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def mask_email_word(email: str) -> str:
    if not email or not _EMAIL_RE.match(email):
        return "****@****"
    try:
        local, domain = email.split("@", 1)
        if len(local) == 1:
            masked_local = "*"
        elif len(local) == 2:
            masked_local = local[0] + "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain.lower()}"
    except Exception:
        return "****@****"

def estimate_token_count(text: str) -> int:
    return len(text) // 4

def get_total_tokens(transcripts: List[Dict[str, Any]]) -> int:
    return sum(estimate_token_count(t["transcript"]) for t in transcripts if t.get("transcript"))

def merge_transcripts(transcripts: List[Dict[str, Any]]) -> str:
    formatted = []
    for t in transcripts:
        if not t.get("transcript"):
            continue
        call_id = t.get("call_id", "unknown_call_id")
        timestamp = t.get("call_date", "unknown_time")
        agent_email = mask_email_word(t.get("agent_email", ""))
        formatted.append(
            f"🟩 call_id: {call_id}\n"
            f"👤 agent_email: {agent_email}\n"
            f"🗓️  call_date: {timestamp}\n\n"
            f"{t['transcript']}"
        )
    return "\n\n---\n\n".join(formatted)

def calculate_confidence(total_tokens: int, expected_min: int = 1) -> float:
    return min(total_tokens / expected_min, 1.0)

def aggregate_audio_features(transcripts: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = [
        "speaking_rate_customer", "speaking_rate_agent", "agent_overlap_rate",
        "customer_filler_count", "agent_pitch_variance", "customer_pitch_variance",
        "agent_silence_ratio", "customer_silence_ratio", "agent_talk_ratio",
        "customer_talk_ratio", "emotion_shift_score", "dominant_speaker"
    ]
    temp = {k: [] for k in keys}
    for t in transcripts:
        af = t.get("audio_features", {})
        for k in keys:
            val = af.get(k)
            if val is not None:
                temp[k].append(val)

    result = {}
    for k, values in temp.items():
        if values:
            if isinstance(values[0], str):
                result[k] = max(set(values), key=values.count)
            else:
                result[k] = sum(values) / len(values)
    return result

def build_mini_rag_payload(transcripts: List[Dict[str, Any]], audio_features: Dict[str, Any] = None) -> Dict[str, Any]:
    merged = merge_transcripts(transcripts)
    total_tokens = get_total_tokens(transcripts)
    confidence = calculate_confidence(total_tokens)
    if not audio_features:
        audio_features = aggregate_audio_features(transcripts)
    if "emotion_shift_score" not in audio_features:
        audio_features["emotion_shift_score"] = 0.0
    if  "sentiment" not in audio_features:
        audio_features["sentiment"] = "neutral"

    messages = build_mini_rag_messages(merged, audio_features=audio_features)
    return {
        "messages": messages,
        "confidence": confidence,
        "token_count": total_tokens,
        "audio_features": audio_features
    }

def build_mini_rag_messages(merged_transcript: str, audio_features: Dict[str, Any] = None) -> List[Dict[str, str]]:
    try:
        system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        knowledge     = KNOWLEDGE_PROMPT_PATH.read_text(encoding="utf-8")
        examples      = EXAMPLES_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        log.error(f"Mini-RAG prompt dosyaları okunamadı: {e}")
        raise

    user_prompt = (
    "Aşağıda bir müşteriye ait birden fazla görüşmenin transkriptleri yer almaktadır. "
    "Bu görüşmelerin tamamını değerlendirerek, sistem mesajında tanımlı JSON formatına uygun analiz üret.\n\n"
    "Eğer ses analiz metrikleri de verilmişse, bunları da değerlendirmeye kat.\n\n"
    "Görüşmeler:\n\n"
    f"{merged_transcript}"
    )

    if audio_features:
        formatted_features = json.dumps(audio_features, indent=2, ensure_ascii=False)
        user_prompt += (
        f"\n\nGörüşmelere ait ses analiz metrikleri (audio_features):\n"
        f"{formatted_features}\n\n"
        "Lütfen her metrik için en az bir cümlelik yorum yaz ve audio_analysis_commentary altında bu yorumları oluştur."
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": knowledge},
        {"role": "user", "content": examples},
        {"role": "user", "content": user_prompt}
    ]

def generate_openai_summary(messages: List[Dict[str, str]], model: str = "gpt-4o-mini", temperature: float = 0.3) -> Dict[str, Any]:
    response = openai_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("OpenAI cevabı boş döndü (content is empty)")
    return json.loads(content)
