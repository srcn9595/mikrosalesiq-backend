from __future__ import annotations

"""insight_utils.py – Insight‑Engine shared helpers (v8‑adaptive)
===================================================================
* v7 + **akıllı örnekleme** (soft_cap/min_cap) & LOG geliştirmeleri.
* Token güvenli, düşük/veri yüksek/veri durumuna otomatik uyum sağlar.
* ENV değişkenleri: INSIGHT_SOFT_CAP, INSIGHT_MIN_CAP, INSIGHT_LOG_LEVEL.
"""

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from openai import APIConnectionError, APITimeoutError, OpenAI, OpenAIError

# ────────────────────────── Logging setup ──────────────────────────
log_level = os.getenv("INSIGHT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | insight_utils | %(message)s",
)
log = logging.getLogger("insight_utils")

# ---------------------------------------------------------------------------
# Config paths (all optional)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent / "config"
EXAMPLES_PROMPT_PATH = ROOT / "prompt_examples.md"
INTENTS_JSON_PATH = ROOT / "intents.json"
_INTENT_PROMPTS_DIR = ROOT / "intent_prompts"

# ---------------------------------------------------------------------------
# Sample‑size hyper‑params (env‑overrideable)
# ---------------------------------------------------------------------------
SOFT_CAP = int(os.getenv("INSIGHT_SOFT_CAP", "100"))  # Ideal örneklem
MIN_CAP = int(os.getenv("INSIGHT_MIN_CAP", "1"))     # Minimum garanti
HARD_CAP = int(os.getenv("INSIGHT_MAX_DOCS", "300"))   # build_insight_messages içi hard sınır

# ---------------------------------------------------------------------------
# Read helpers – silent if file missing, with DEBUG traces
# ---------------------------------------------------------------------------

def _read(path: Path, default: str = "") -> str:
    if not path.exists():
        log.debug("📄 %s bulunamadı, default kullanılacak.", path.name)
        return default
    try:
        data = path.read_text(encoding="utf-8")
        log.debug("📄 %s yüklendi (%d bayt).", path.name, len(data))
        return data
    except Exception as e:
        log.warning("⚠️ %s okunamadı: %s", path.name, e)
        return default

_EXAMPLES = _read(EXAMPLES_PROMPT_PATH)

try:
    _INTENTS: Dict[str, Dict[str, Any]] = {
        row["intent"]: row for row in json.loads(_read(INTENTS_JSON_PATH, "[]"))
    }
    log.info("🔧 intents.json: %d intent tanımlı.", len(_INTENTS))
except Exception as e:
    log.warning("⚠️ intents.json parse edilemedi: %s", e)
    _INTENTS = {}

# ---------------------------------------------------------------------------
# Token counter – optional tiktoken
# ---------------------------------------------------------------------------
try:
    import tiktoken  # type: ignore

    _enc = tiktoken.get_encoding("cl100k_base")

    def _tokens(txt: str) -> int:  # precise
        return len(_enc.encode(txt))
except Exception:  # pragma: no cover

    def _tokens(txt: str) -> int:  # approx 4 chars / token
        return len(txt) // 4

# ---------------------------------------------------------------------------
# LLM runner (centralised)
# ---------------------------------------------------------------------------
_openai = OpenAI()
MODEL = os.getenv("INSIGHT_MODEL", "gpt-4o-mini")
TEMP = float(os.getenv("INSIGHT_TEMP", "0.3"))


def run_llm(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Send chat to OpenAI, return parsed dict; errors under `error`."""
    t0 = time.time()
    try:
        resp = _openai.chat.completions.create(
            model=MODEL,
            temperature=TEMP,
            messages=messages,
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - t0
        log.info("✅ LLM tamam (%.1f sn, %d mesaj)", elapsed, len(messages))
        log.info("🟢 LLM'den dönen RAW output: %s", resp.choices[0].message.content)
        return json.loads(resp.choices[0].message.content or "{}")
    except (OpenAIError, APIConnectionError, APITimeoutError, json.JSONDecodeError) as e:
        log.error("❌ OpenAI hata: %s", e)
        return {"error": str(e)}

# ---------------------------------------------------------------------------
# Intent prompt helper
# ---------------------------------------------------------------------------

def _intent_prompt(intent: str) -> str:
    fp = _INTENT_PROMPTS_DIR / f"{intent}.md"
    return _read(fp)

# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _truncate(val: Any, max_len: int = 400) -> str:
    txt = str(val) if val is not None else ""
    return txt[: max_len - 1] + "…" if len(txt) > max_len else txt


def _extract_project_fields(pipeline: Sequence[Dict[str, Any]] | None) -> Set[str]:
    fields: Set[str] = set()
    if pipeline:
        for st in pipeline:
            proj = st.get("$project") if isinstance(st, dict) else None
            if proj:
                fields.update(proj.keys())
    return fields


def _get_nested(doc: Dict[str, Any], dotted: str):
    cur: Any = doc
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur

# ---------------------------------------------------------------------------
# Message builder – AKILLI ÖRNEKLEM
# ---------------------------------------------------------------------------

def _sample_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    total = len(docs)
    target = min(total, HARD_CAP)

    if total < MIN_CAP:
        return docs  # Yeterince yoksa tümünü döndür

    if target > SOFT_CAP:
        target = SOFT_CAP

    # Token limiti kontrolü – iteratif küçültme
    while target > 10:
        snap_test = "\n".join(str(d) for d in docs[:target])
        if _tokens(snap_test) + _tokens(_EXAMPLES) < 12_000:
            break
        target //= 2

    if total > target:
        sampled = random.sample(docs, k=target)
        log.debug("🎯 Rastgele örneklem: %d/%d", target, total)
        return sampled
    return docs


def build_insight_messages(
    docs: List[Dict[str, Any]],
    *,
    intent: str,
    query: Optional[str] = None,
    pipeline: Optional[Sequence[Dict[str, Any]]] = None,
    max_tokens: int = 12_000,
) -> List[Dict[str, str]]:
    docs = _sample_docs(docs)
    log.debug("→ build_messages intent=%s örneklem=%d", intent, len(docs))

    meta = _INTENTS.get(intent, {})
    desc = meta.get("description", "")

    proj_fields = _extract_project_fields(pipeline)
    default_fields = {"lost_reason", "lost_reason_detail", "opportunity_owner"}
    show_fields = proj_fields or default_fields

    def _snapshot(limit: int) -> str:
        lines: List[str] = [f"INTENT: {intent} — {desc}"]
        if query:
            lines.append(f"USER QUESTION: {query}")
        if pipeline:
            lines.append(f"PIPELINE: {json.dumps(pipeline, default=str, ensure_ascii=False)[:300]}…")
        lines.append(f"\nDATA SNAPSHOT (≤{limit}):\n")

        lines.append(f"🔎 Toplam analiz edilen kayıt sayısı: {len(docs[:limit])}")
        if len(docs) < MIN_CAP:
            lines.append(f"⚠️ Uyarı: Minimum örneklem ({MIN_CAP}) sağlanamadı, mevcut {len(docs)} kayıt analiz ediliyor.")
        lines.append(f"\nDATA SNAPSHOT (≤{limit}):\n")

        for d in docs[:limit]:
            parts = [f"🧾 {d.get('customer_num', '?')}"]
            for fld in sorted(show_fields):
                val = _get_nested(d, fld)
                if val not in (None, ""):
                    parts.append(f"{fld}: {_truncate(val, 60)}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    # progressive reduction (limit üstünde ayrıca token check yaptık)
    for cut in (100, 50, 20, 10):
        snap = _snapshot(cut)
        if _tokens(snap) + _tokens(_EXAMPLES) < max_tokens:
            break
    else:
        snap = _snapshot(3)

    messages: List[Dict[str, str]] = []
    intent_extra = _intent_prompt(intent).strip()
    if intent_extra:
        messages.append({"role": "assistant", "content": intent_extra})

    if _EXAMPLES.strip():
        messages.append({"role": "assistant", "content": _EXAMPLES.strip()})

    messages.append({"role": "user", "content": snap})

    log.info("👀 LLM’e giden snapshot: %s", snap)
    log.info("📨 Mesaj token≈%d", sum(_tokens(m["content"]) for m in messages))
    return messages

# ---------------------------------------------------------------------------
# Output normalisation
# ---------------------------------------------------------------------------

_BASE: Dict[str, Any] = {
    "result": "",
    "message": ""
}


def format_insight_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(_BASE)
    for k, v in raw.items():
        if k == "next_steps" and isinstance(v, dict):
            merged = dict(out["next_steps"])
            merged.update(v)
            out["next_steps"] = merged
        else:
            out[k] = v
    log.debug("↩︎ format_output keys=%s", list(raw.keys()))
    return out
