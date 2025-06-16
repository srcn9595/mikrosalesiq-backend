# services/executor_api/mini_rag/mini_rag_utils.py

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from openai import OpenAI

log = logging.getLogger("mini_rag_utils")

# 🔧 mini_rag_config klasörünü doğru şekilde referans al
ROOT = Path(__file__).parent / "mini_rag_config"
SYSTEM_PROMPT_PATH    = ROOT / "system_prompt.txt"
KNOWLEDGE_PROMPT_PATH = ROOT / "prompt_knowledge.md"
EXAMPLES_PROMPT_PATH  = ROOT / "prompt_examples.md"

# 🔐 OpenAI client (sync)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
        agent_email = t.get("agent_email", "unknown_agent")
        formatted.append(
            f"🟩 call_id: {call_id}\n"
            f"👤 agent_email: {agent_email}\n"
            f"🗓️  call_date: {timestamp}\n\n"
            f"{t['transcript']}"
        )
    return "\n\n---\n\n".join(formatted)


def calculate_confidence(total_tokens: int, expected_min: int = 1) -> float:
    return min(total_tokens / expected_min, 1.0)

def build_mini_rag_payload(transcripts: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged = merge_transcripts(transcripts)
    total_tokens = get_total_tokens(transcripts)
    confidence = calculate_confidence(total_tokens)
    messages = build_mini_rag_messages(merged)
    return {
        "messages": messages,
        "confidence": confidence,
        "token_count": total_tokens
    }


def build_mini_rag_messages(merged_transcript: str) -> List[Dict[str, str]]:
    try:
        system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        knowledge     = KNOWLEDGE_PROMPT_PATH.read_text(encoding="utf-8")
        examples      = EXAMPLES_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        log.error(f"Mini-RAG prompt dosyaları okunamadı: {e}")
        raise

    user_prompt = f"Aşağıda müşteriyle yapılmış bir görüşme yer almaktadır:\n\n{merged_transcript}"

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
