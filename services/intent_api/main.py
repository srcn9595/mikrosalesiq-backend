# ───────────────────────── services/intent_api/main.py ─────────────────────
from fastapi import FastAPI, Request
from datetime import datetime,timezone
import os, json, pathlib
from openai import OpenAI
from langfuse import Langfuse
from dotenv import load_dotenv
import logging
from bson import json_util
import re
from typing import List  
from datetime import datetime, timedelta
from openai.types.chat import ChatCompletionMessageToolCall

ROOT_DIR   = pathlib.Path(__file__).parent
CONFIG_DIR = ROOT_DIR / "config"
load_dotenv(ROOT_DIR / ".env")


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)

# ── statik dosyalar ---------------------------------------------------------
SYSTEM_PROMPT = (CONFIG_DIR / "system_prompt.txt").read_text(encoding="utf-8")
TOOL_MANIFEST = json.loads((ROOT_DIR / "tool_manifest.json").read_text())
_REL_RE = re.compile(r"{today([+-]\d+)([dwmy])}")
# ── FastAPI + OpenAI + Langfuse --------------------------------------------
app = FastAPI()

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ───────────────────────── call-level algısı ─────────────────────────

# intent düzeyi haritası
INTENT_LEVEL_MAP = {
    # ───── call-level intent’ler ─────
    "cleaned_transcript": "call",
    "file_path": "call",
    "duration": "call",
    "call_date": "call",
    "agent_email": "call",
    "agent_name": "call",
    "get_call_dates": "call",
    "get_last_call": "call",
    "get_transcript_by_call_id": "call",
    "get_transcripts_by_customer_num": "call",
    "get_sales_scores": "call",
    "get_summary_by_call": "call",
    "semantic_search": "call",

    # ───── customer-level intent’ler ─────
    "contact_email": "customer",
    "contact_name": "customer",
    "customer_num": "customer",
    "opportunity_stage": "customer",
    "product_lookup": "customer",
    "lead_source": "customer",
    "close_date": "customer",
    "created_date": "customer",
    "lost_reason": "customer",
    "get_call_metrics": "customer",
    "get_conversion_probability": "customer",
    "get_risk_score": "customer",
    "get_next_steps": "customer",
    "get_audio_analysis_commentary": "customer",
    "get_sentiment_analysis": "customer",
    "get_customer_overview": "customer",
    "get_customer_products": "customer",
    "get_opportunity_info": "customer",
    "get_contact_info": "customer",
    "get_personality_and_sector": "customer",
    "vector_customer_similarity_search": "customer",
    "get_customer_patterns": "customer",

    # ───── insight intent’ler ─────
    "insight_customer_loss_reasons": "customer",
    "insight_success_patterns": "customer",
    "insight_customer_tactics": "customer",
    "insight_risk_profiles": "customer",
    "insight_customer_recovery": "customer",
    "insight_agent_communication": "customer"
}



def _convert_iso_dates(obj):
    """
    Pipeline içindeki ISO-8601 string’leri timezone-aware datetime.datetime’e çevirir.
    Z dönüşümlerde UTC kullanır; TZ yoksa naive bırakır (gerekirse +03:00 ekleyin).
    """
    if isinstance(obj, dict):
        return {k: _convert_iso_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_iso_dates(v) for v in obj]
    if isinstance(obj, str) and _ISO_RE.match(obj):
        # "2025-06-12T00:00:00Z"  →  dt(2025,6,12,0,0,tzinfo=UTC)
        dt = datetime.fromisoformat(obj.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)  # UTC kaydediyorsanız
    return obj

def is_call_level_intent(intent: str) -> bool:
    return INTENT_LEVEL_MAP.get(intent) == "call"

def is_vector_based_tool(name: str) -> bool:
    return name in ("vector_call", "vector_customer")

def fix_pipeline_keys_and_operators(obj):
    """
    Tüm dict key’lerindeki ve string operator değerlerindeki baştaki boşlukları düzeltir.
    Rekürsif çalışır. Hem {" $gte": ...} hem de "$first": " $something" gibi yapıları düzeltir.
    """
    if isinstance(obj, dict):
        new_obj = {}
        for k, v in obj.items():
            new_key = k.lstrip() if isinstance(k, str) else k
            new_val = fix_pipeline_keys_and_operators(v)
            if isinstance(new_val, str) and new_val.lstrip().startswith("$"):
                new_val = new_val.lstrip()
            new_obj[new_key] = new_val
        return new_obj
    elif isinstance(obj, list):
        return [fix_pipeline_keys_and_operators(i) for i in obj]
    else:
        return obj



def pipeline_is_call_level(pipeline: list[dict]) -> bool:
    """
    Pipeline’da $unwind "$calls" VARSA veya
    herhangi bir stage 'calls.' ile başlayan alan kullanıyorsa TRUE döner.
    """
    for stage in pipeline:
        # 1) $unwind
        if "$unwind" in stage:
            uw = stage["$unwind"]
            if (isinstance(uw, str)  and uw.startswith("$calls")) or \
               (isinstance(uw, dict) and uw.get("path") == "$calls"):
                return True

        # 2) $match / $project / $sort vs.
        for op in ("$match", "$project", "$sort"):
            if op in stage and any(k.startswith("calls.") for k in stage[op]):
                return True
    return False

def ensure_call_id(pipeline: list[dict], intent: str) -> list[dict]:
    """
    Eğer intent call-level ise ve pipeline da öyle görünüyorsa
    $project aşamasına call_id ekler.
    """
    if not is_call_level_intent(intent):
        return pipeline

    if not pipeline_is_call_level(pipeline):
        return pipeline

    for st in pipeline:
        if "$project" in st:
            st["$project"].setdefault("call_id", "$calls.call_id")
            st["$project"].setdefault("_id", 0)
            return pipeline

    pipeline.append({"$project": {"_id": 0, "call_id": "$calls.call_id"}})
    return pipeline

# ───────────────────────── helpers ─────────────────────────────────────────
def _resolve_relative_dates(text: str) -> str:
    """
    {today±Nd}, {today±Nw}, {today±Nm}, {today±Ny} makrolarını
    gerçek ISO-8601 tarihlere çevirir.
    """
    def _sub(m):
        offset = int(m.group(1))
        unit   = m.group(2)
        base   = datetime.utcnow().date()

        if unit == "d":
            real = base + timedelta(days=offset)
        elif unit == "w":
            real = base + timedelta(weeks=offset)
        elif unit == "m":
            # Ay için kaba ≈30 gün (gelişmiş ihtiyaçta dateutil.relativedelta kullanın)
            real = base + timedelta(days=30 * offset)
        elif unit == "y":
            real = base + timedelta(days=365 * offset)
        else:
            return m.group(0)           # bilinmeyen; dokunma

        return real.isoformat()
    return _REL_RE.sub(_sub, text)

CANON = {
    # ───────── İçerik alanları ─────────
    r"(özet|analiz|summary)":                "summary",
    r"(profil|profile|müşteri profili)":     "customer_profile",
    r"(skor|puan|score)":                    "sales_scores",
    r"(öneri|recommendation|tavsiye)":       "recommendations",
    r"(transkript|metin|clean text)":        "cleaned_transcript",
    r"(süre|duration|kaç.?dk|kaç.?sn)":      "duration",

    # ───────── CRM alanları ─────────
    r"(paket|ürün|module|product)":          "product_lookup",
    r"(stage|aşama|fırsat.?aşaması)":        "opportunity_stage",
    r"(kaynak|lead source)":                 "lead_source",
    r"(close date|kapanış.?tarihi)":         "close_date",
    r"(lost reason|kaybedilme.?sebebi)":     "lost_reason",
    r"(contact.?email|iletişim.?eposta)":    "contact_email",
    r"(contact.?name|iletişim.?adı)":        "contact_name",
}



def extract_fields(query: str) -> List[str]:
    found = [
        canon
        for pattern, canon in CANON.items()
        if re.search(pattern, query, re.I)      # ‼️ re.escape YOK
    ]
    return list(dict.fromkeys(found))


def build_messages(user_query: str) -> list[dict]:
    today_iso = datetime.utcnow().date().isoformat()

    # statik dosyalar
    schema_json   = (CONFIG_DIR / "schema_registry.json").read_text()
    heuristics_md = (CONFIG_DIR / "heuristics.md").read_text()
    examples_md   = (CONFIG_DIR / "prompt_examples.md").read_text()
    intents_json  = (CONFIG_DIR / "intents.json").read_text()

    # önce {today} makrosu
    sys_prompt = SYSTEM_PROMPT.replace("{today}", today_iso)

    # prompt dosyalarının hepsine aynı işlemi uygulamak gerekebilir
    # (örneklerde de {today-…} geçiyorsa)
    sys_prompt = _resolve_relative_dates(sys_prompt)
    examples_md = _resolve_relative_dates(examples_md)

    wanted_fields = extract_fields(user_query)
    fields_hint   = "**User-requested fields:** " + (
        ", ".join(wanted_fields) if wanted_fields else "(default)"
    )

    sys_prompt = (
        sys_prompt
        .replace("{{fields_hint}}",      fields_hint)
        .replace("{{schema_registry}}",  schema_json)
        .replace("{{heuristics}}",       heuristics_md)
        .replace("{{prompt_examples}}",  examples_md)
        .replace("{{intents_json}}",     intents_json)
    )

    # son olarak “JSON döndür” hatırlatıcısı
    sys_prompt = "You MUST answer in valid JSON.\n\n" + sys_prompt

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": user_query},
    ]


def normalize_plan(raw):
    """
    OpenAI cevabını tek listeye indirger – list[{name,arguments}]
    """

    # 0️⃣  Model yalnızca **tek** fonksiyon çağrısı döndürdüyse
    #     {"name": "...", "arguments": {...}}
    if isinstance(raw, dict) and "name" in raw and "arguments" in raw:
        return [raw]                       #  ←  YENİ SATIR

    # ①  Düz liste
    if isinstance(raw, list):
        if len(raw) == 1 and raw[0].get("name") == "multi_tool_use.parallel":
            return raw[0]["arguments"]["tool_uses"]
        return raw

    # ②  2024-03 chat formatı
    if "tool_calls" in raw:
        return raw["tool_calls"]

    # ③  parallel wrapper
    if raw.get("name") == "multi_tool_use.parallel":
        return raw["arguments"]["tool_uses"]

    # ④  {'plan':[...]} + içi parallel
    if "plan" in raw and isinstance(raw["plan"], list):
        lst = raw["plan"]
        if len(lst) == 1 and lst[0].get("name") == "multi_tool_use.parallel":
            return lst[0]["parameters"]["tool_uses"]
        return lst

    # ⑤  {'tool_call': {...}}
    if "tool_call" in raw:
        return [raw["tool_call"]]

    raise ValueError("Unknown plan format")

def tidy(step: dict) -> dict:
    """
    Executor’un beklediği forma çevirir:
      {'name': '...', 'arguments': {...}}
    """
    # 0) nested parallel → içindekileri çöz
    if step.get("name") == "multi_tool_use.parallel":
        return [tidy(s) for s in step["parameters"]["tool_uses"]]

    # 1) zaten doğru form
    if "name" in step and "arguments" in step:
        step["name"] = step["name"].removeprefix("functions.")
        if "intent" in step:
            step["intent"] = step["intent"]
        return step

    # 2) OpenAI parallel elemanı
    if "recipient_name" in step and "parameters" in step:
        name = step["recipient_name"].removeprefix("functions.")
        step["name"] = step["name"].removeprefix("functions.")
        return {"name": name, "arguments": step["parameters"]}

    # 3) Basit {'name', 'parameters'} formu
    if "name" in step and "parameters" in step:
        return {"name": step["name"], "arguments": step["parameters"]}

    raise ValueError(f"Unknown step format: {step}")

# ───────────────────────── endpoint ─────────────────────────────────────────
@app.post("/analyze")
async def analyze(req: Request):
    query = (await req.json()).get("query", "")

    # ① Root span: intent_detection
    with langfuse.start_as_current_span(
        name="intent_detection",
        input={"query": query},
        metadata={"service": "intent_api"}
    ) as root_span:

        try:
            # ② Generation span: openai.plan
            with langfuse.start_as_current_generation(
                name="openai.plan",
                model="gpt-4o-mini",
                input={"messages": build_messages(query)}
            ) as gen:

                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    tools=TOOL_MANIFEST,
                    messages=build_messages(query),
                    response_format={"type": "json_object"},
                    temperature=0,
                )

                msg_raw = resp.choices[0].message
                if msg_raw.tool_calls:                      
                     raw = [
                        {                                 
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments)
                  }
                   for tc in msg_raw.tool_calls       
                ]
                else:                                       
                    raw = json.loads(msg_raw.content)
                try:
                    steps   = normalize_plan(raw)
                except Exception as e:
                        logging.error("normalize_plan – ham cevap: %s", raw)   # 👈
                        raise    

                plan = []
                for s in steps:
                    t = tidy(s)
                    if isinstance(t, list):
                        plan.extend(t)
                        continue

                    if t["name"] == "mongo_aggregate":
                        pl = t["arguments"].get("pipeline", [])
                        pl = fix_pipeline_keys_and_operators(pl)
                        logging.log(logging.DEBUG, "⏮️  Pipeline-raw:\n%s",
                            json.dumps(pl, default=json_util.default, indent=2))
                        pl = _convert_iso_dates(pl)
                        logging.log(logging.DEBUG, "⏮️  Pipeline-chaned:\n%s",
                            json.dumps(pl, default=json_util.default, indent=2))
                        intent = t.get("intent", "")
                        t["arguments"]["pipeline"] = ensure_call_id(pl, intent)

                    if is_vector_based_tool(t["name"]):
                        args = t["arguments"]
                        args.setdefault("top_k", 5)
                        args.setdefault("threshold", 0.75)
                        if t["name"] == "vector_customer":
                            args.setdefault("embedding_type", "customer_level")
                            args.setdefault("collection", "audio_jobs")
                        else:
                            args.setdefault("embedding_type", "call_level")

                    plan.append(t)


                # ③ Generation span’a sonucu kaydet
                gen.update(output={"plan": plan})

            # ④ Root span’a sonucu da ekleyebilirsiniz
            root_span.update(output={"plan": plan})
            return {"plan": plan}

        except Exception as exc:
            root_span.update(output={"error": str(exc)})
            # İsterseniz hatayı yeniden fırlatın veya JSON dönün
            return {"plan": [], "error": str(exc), "query": query}

    # ⑤ Flush (opsiyonel)
    langfuse.flush()

