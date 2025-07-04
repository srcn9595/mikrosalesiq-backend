#!/usr/bin/env python3
# clean_transcripts.py
"""
audio_jobs  ➜  OpenAI GPT ile gürültü/tekrar temizliği
------------------------------------------------------
• calls[].cleaned_transcript eksik olan her kaydı işler
• uzun metinleri parçalar, sırayı koruyarak yeniden birleştirir
• MongoDB’ye yazar + cleaned_output/<customer>/<call_id>.txt olarak kaydeder
"""
from __future__ import annotations
import os, json, time, logging, itertools
from pathlib import Path
from typing import List

import backoff                 
from dotenv import load_dotenv
from pymongo import MongoClient
from rich.progress import track 
import tiktoken                 
import openai                   

# ─────────────────────────────── Ayarlar ────────────────────────────────
load_dotenv()

MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME     = "alotech"
COLL_NAME   = "audio_jobs"

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")              
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")   
TEMPERATURE     = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
CHUNK_TOKENS    = int(os.getenv("MAX_CHUNK_TOKENS", "12000"))
MAX_RETRIES     = int(os.getenv("MAX_RETRIES", "4"))

openai.api_key = OPENAI_API_KEY
enc = tiktoken.encoding_for_model(OPENAI_MODEL)

PROMPT_SYS = (
    "Sen Parasut adlı bir muhasebe, faturalama ve ön muhasebe yazılımı için çalışan "
    "deneyimli bir transkript düzenleyicisisin. Bu yazılımı kullanan müşterilerle yapılan "
    "telefon görüşmelerinin yazıya dökülmüş halini temizleyeceksin.\n\n"

    "Whisper gibi otomatik transkripsiyon araçları bazen şu hataları yapar:\n"
    "- Aynı kelime veya cümleyi art arda tekrar eder (örneğin: 'merhaba merhaba merhaba')\n"
    "- Karşılıklı konuşmaları birleştirir veya karıştırır\n"
    "- Anlamsız kelime/harf dizileri oluşturur (örn: 'abc cba xyz')\n\n"

    "Senin görevin:\n"
    "1. Metindeki tekrarları ve bozuklukları kaldırmak\n"
    "2. Anlamlı, okunabilir bir diyalog yapısı oluşturmak\n"
    "3. Konuşmacılar arasındaki sırayı bozmamak\n"
    "4. Aynı konuşmacıya ait ardışık cümleleri birleştirebilirsin\n"
    "5. Ancak farklı konuşmacılara ait cümleler kesinlikle aynı satıra yazılamaz\n"
    "6. Hiçbir bilgi ekleme, çıkarma ya da değiştirme – sadece düzeltme yap\n\n"

    "Bu konuşmalar genellikle şunları içerir:\n"
    "- Fatura işlemleri, lisans yenileme, kontör/bakiye sorguları\n"
    "- VKN, şirket adı, e-posta gibi müşteri bilgileri\n"
    "- E-fatura, mali mühür, kurulum randevusu vb.\n\n"

    "Ek kurallar:\n"
    "- Görüşmelere genellikle Temsilci başlar.\n"
    "- Bir kişi kendisini 'Ben [isim] Paraşüt’ten' diyerek tanıtıyorsa, bu kişi Temsilci’dir.\n"
    "- '@parasut.com' uzantılı e-posta adresleri Temsilci’ye aittir.\n"
    "- '05xx...' ile başlayan ifadeler genellikle müşteriyi temsil eder.\n"
    "- Bu bilgiler ışığında, eğer konuşmacı etiketleri karışmışsa doğru şekilde düzelt.\n"
    "- Konuşmacılar yanlış atanmışsa bile düzeltme yapmaktan çekinme.\n\n"

    "Temsilci e-postası: {agent}, Müşteri telefonu: {cust}\n\n"

    "Yalnızca temizlenmiş metni döndür. JSON, yorum, açıklama, etiket ekleme.\n"
    "Metni her satırda 'Temsilci:' veya 'Müşteri:' etiketiyle sun. Örnek:\n"
    "Temsilci: Merhaba, Paraşüt’ten arıyorum.\n"
    "Müşteri: Merhaba, buyurun."
)

PROMPT_TMPL = (
    "Agent (Temsilci): {agent}\n"
    "Customer (Müşteri): {cust}\n\n"
    "{text}"
)

# ─────────────────────────────── Yardımcılar ────────────────────────────
def num_tokens(text: str) -> int:
    return len(enc.encode(text))

def chunks_by_tokens(text: str, limit: int) -> List[str]:
    """limit'ten büyükse satır bazlı parçalar döndür."""
    if num_tokens(text) <= limit:
        return [text]

    parts, buf = [], []
    for line in text.splitlines():
        buf.append(line)
        if num_tokens("\n".join(buf)) >= limit:
            # taşmadan önceki satıra kadar al
            parts.append("\n".join(buf[:-1]))
            buf = [line]
    if buf:
        parts.append("\n".join(buf))
    return parts

@backoff.on_exception(backoff.expo,
                      (openai.OpenAIError, TimeoutError),
                      max_tries=MAX_RETRIES,
                      factor=2)
def gpt_clean(text: str, cust: str, agent: str) -> str:
    prompt = PROMPT_TMPL.format(agent=agent, cust=cust, text=text)

    resp = openai.chat.completions.create(
        model       = OPENAI_MODEL,
        temperature = TEMPERATURE,
        messages    = [
            {"role": "system", "content": PROMPT_SYS},
            {"role": "user",   "content": prompt}
        ]
    )
    return resp.choices[0].message.content.strip()

# ─────────────────────────────── Ana işlem ──────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%H:%M:%S")

    client = MongoClient(MONGO_URI)
    coll   = client[DB_NAME][COLL_NAME]

    cur = coll.find({
        "calls.status": "downloaded",
        "calls.cleaned_transcript": {"$exists": False}
    })

    total_calls = sum(len([c for c in doc["calls"]
                           if c["status"]=="downloaded" and
                              not c.get("cleaned_transcript")])
                      for doc in cur.clone())  # clone(): kursoru tüketmeden say
    logging.info("İşlenecek toplam çağrı: %s", total_calls)

    for doc in cur:
        cust_num = doc["customer_num"]
        for call in track(
            [c for c in doc["calls"]
             if c["status"]=="downloaded" and not c.get("cleaned_transcript")],
            description=f"[bold cyan]{cust_num}"
        ):
            call_id  = call["call_id"]
            agent    = call.get("agent_email", "Temsilci")

            raw_path = Path("output") / cust_num / f"{call_id}.txt"
            if not raw_path.exists():
                logging.warning("Metin dosyası yok: %s", raw_path)
                continue
            text = raw_path.read_text(encoding="utf-8")

            # → açık-uç token kontrolü & parça işleme
            cleaned_parts = []
            for part in chunks_by_tokens(text, CHUNK_TOKENS):
                cleaned_parts.append(gpt_clean(part, cust_num, agent))
            cleaned = "\n".join(cleaned_parts)

            # Mongo güncelle
            coll.update_one(
                {"_id": doc["_id"], "calls.call_id": call_id},
                {"$set": {"calls.$.cleaned_transcript": cleaned}}
            )

            # diske yaz
            cdir = Path("cleaned_output") / cust_num
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / f"{call_id}.txt").write_text(cleaned, encoding="utf-8")

    logging.info("✅  Tüm temizlik işlemleri tamamlandı")

if __name__ == "__main__":
    main()
