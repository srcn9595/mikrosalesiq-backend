
## 1 · Alan Tanıma Kuralları
1.  'ast' ile başlayan dize → **call_id**

2. 05 … ile başlayan 11 haneli sayı → **customer_num**  
   · Doğrudan `audio_jobs.customer_num` alanıyla eşleştirilir.

3.  “@parasut.com” ile biten dize → **agent_email**

4.  Açık tarih ifadesi (ör. `2024-05-01`, `1 Mayıs 2024`, “dün”) → **call_date**  
    · Belirsiz tarih (“dün”, “geçen hafta”, “az önce”) → bugünün ({today}) tarihine göre ISO-8601 biçimine dönüştür.

5.  Süre ifadesi (“50 sn’den uzun”, “2 – 5 dk”) → **duration**  
    ```json
    {
      "value": 50,
      "unit": "second",          // second | minute
      "operator": "gt"           // eq | lt | gt | between
    }
    ```

6.  Yön (direction) anahtar kelimeleri  
    · “beni arayan”, “gelen arama” → `direction = "inbound"`  
    · “aradığım”, “aradığımız müşteri” → `direction = "outbound"`

7.  Birden fazla `call_id`, `customer_num` veya tarih aralığı geçiyorsa → ilgili alanı **dizi** olarak çıkar.

8.  **Göreli (belirsiz) tarih ifadeleri**  
    Aşağıdaki kalıplar, bugünün ({today}) tarihine göre ISO-8601 string’lerine çevrilir ve  
    pipeline’da **calls.call_date** alanına `$gte / $lte` şeklinde yansıtılır.

    | İfade                   | $gte                  | $lte                  | Açıklama |
    |-------------------------|-----------------------|-----------------------|----------|
    | “dün”                  | {today-1d}             | {today-1d}            | Tek gün |
    | “son 7 gün”, “geçen hafta” | {today-7d}         | {today-1d}            | Aralık |
    | “1 hafta önce”         | {today-7d}             | {today-7d}            | Tek gün |
    | “1 ay önce”            | {today-30d}            | {today-30d}           | Tek gün |
    | “son 30 gün”           | {today-30d}            | {today}               | Aralık |
    | “12 Haz 2024 – 12 Haz 2025” | 2024-06-12        | 2025-06-12            | Belirtilen aralık |
    | “12.05.2023 – 12.05.2024”   |	2023-05-12	      | 2024-05-12	          |Gün • Ay • Yıl aralığı
    
9.  “Closed Won”, “Closed Lost”, “Prospecting”, “Kazanıldı”, “Kaybedildi” → **opportunity_stage**

10. “kaynak”, “lead kaynağı”, “lead_source” → **lead_source**

11. “kapanış tarihi”, “close date”, “kapanma tarihi” → **close_date**

12. “oluşturulma tarihi”, “created date”, “ilk kayıt” → **created_date**

13. “paket(ler)”, “ürün listesi”, “product_lookup” → **product_lookup**

14. “kaybedilme sebebi”, “lost reason” → **lost_reason**

15. “iletişim e-posta”, “müşteri e-postası”, “contact_email” → **contact_email**

16. “iletişim adı”, “müşteri adı”, “contact_name” → **contact_name**

---

## 2 · İstenen Çıktıyı Belirleme Kuralları
> Kullanıcı hangi alanı talep ediyor?

| Anahtar Kelimeler | target / intent | Açıklama |
|---|---|---|
| “transkript”, “metin”, “yazıya dök” | `cleaned_transcript` | `audio_jobs.calls.cleaned_transcript`; yoksa kuyruğa alınır. |
| “ses kaydı”, “wav”, “mp3” | `file_path` | Ses dosyasının S3 anahtarı / URL’si → `audio_jobs.calls.file_path`. |
| “süre”, “kaç saniye”, “kaç dk” | duration | Toplam konuşma süresi (audio_jobs.calls.duration). |
| **“kaç”, “toplam”, “ortalama”, “en uzun”, “kaç farklı”**| **`get_call_metrics`**| Toplam/ortalama süre, çağrı sayısı, farklı kişi sayısı vb. özet istatistikleri döner.|
| “kim”, “kimle”, “kiminle” (+agent) | `contact_num` | Agent merkezli sorguda müşteri numarası (Inbound → `caller_id`, Outbound → `called_num`). |
| “paket”, “ürün”, “product” | `product_lookup` | Satın alınan paket / modül → `audio_jobs.product_lookup`. |
| “kapanış tarihi”, “close date” | `close_date` | `audio_jobs.close_date`. |
| “fırsat aşaması”, “opportunity stage”, “kazanıldı mı” | `opportunity_stage` | `audio_jobs.opportunity_stage`. |
| “lead kaynağı”, “kaynak” | `lead_source` | `audio_jobs.lead_source`. |
| “kaybedilme sebebi”, “lost reason” | `lost_reason` | `audio_jobs.lost_reason` veya `lost_reason_detail`. |
| “müşteri e-postası”, “iletişim e-posta” | `contact_email` | `audio_jobs.contact_email`. |
| “müşteri adı”, “iletişim adı” | `contact_name` | `audio_jobs.contact_name`. |
| “dönüşüm olasılığı”, “convert olasılığı”, “alış yapma ihtimali” | `conversion_probability` | Müşteri dönüşüm olasılığı (`mini_rag.conversion_probability`). |
| “risk puanı”, “risk skoru” | `risk_score` | Satış riski (`mini_rag.risk_score`). |
| “önerilen adımlar”, “takip adımları”, “next step”, “ne yapılmalı” | `next_steps` | `mini_rag.next_steps`; hem `for_customer` hem `for_agent`. |
| “duygusal dalgalanma”, “emotion shift”, “duygu geçişi” | `emotion_shift_score` | `mini_rag.audio_analysis.emotion_shift_score`. |
| “genel ruh hali”, “duygu durumu”, “sentiment” | `sentiment` | `mini_rag.audio_analysis.sentiment`. |
| “duygu yorumu”, “ses analizi yorumu”, “yorumlar” | `audio_analysis_commentary` | `mini_rag.audio_analysis.audio_analysis_commentary`. |
| “birleşik metin”, “merged transcript” | `merged_transcript` | `mini_rag.merged_transcript`; tüm çağrıların tek metni. |
| “genel özet”, “toplam değerlendirme”, “müşteri özeti” | `summary` | `get_advanced_insight` çıktısıdır; müşteri seviyesinde genel analiz sunar. |
| “öneri”, “ne yapmalıyız”, “ne önerirsin”, “aksiyon”, “takip planı” | `recommendations` | `get_advanced_insight` çıktısıdır; stratejik tavsiye ve aksiyon listesi döner. |
| “temsilci eksikleri”, “iletişim hataları”, “süreç sorunu”, “problemli davranış” | `agent_patterns` | `get_advanced_insight` çıktısıdır; temsilcilerde gözlemlenen yaygın hataları döner. |
| “müşteri segmenti”, “zor müşteri”, “kolay müşteri”, “segment analizi” | `segments` | `get_advanced_insight` çıktısıdır; müşteri türlerini ve segmentleri döner. |
| “yaygın sorunlar”, “müşteri şikayetleri”, “itirazlar”, “engeller” | `common_issues` | `get_advanced_insight` çıktısıdır; müşterilerin en sık karşılaştığı sorunları listeler. |
| “not”, “ek bilgi”, “özel durum”, “önemli detay” | `note` | `get_advanced_insight` çıktısıdır; analiz sonunda opsiyonel açıklama sunar. |



> Model tabloda eşleşme bulamazsa **varsayılan** olarak “transkript” (`cleaned_transcript`) alanını getirir.

---

## 2.1 · Heuristik Kural: `$project` İçine `call_id` yalnızca **call-level** sorgular için eklenmelidir

- **Kural:**  
  - Eğer intent  `cleaned_transcript`, `file_path`, `duration`, `call_date`, `agent_name`, `agent_email` gibi **call-level** alanlardaysa,  
    `$project` aşamasına mutlaka `call_id` eklenmelidir.  
  - Eğer intent `opportunity_stage`, `lead_source`, `contact_email`, `contact_name`, `product_lookup`, `close_date`, `lost_reason`, `created_date` gibi **customer-level** alanlardaysa,  
    `call_id` **gereksizdir** ve `$project` aşamasına **eklenmemelidir**.

- **Neden?**  
  - `call_id`, sadece `audio_jobs.calls[]` içindeki **çağrı seviyesinde** geçerli bir alandır.  
  - `audio_jobs` düzeyindeki müşteri seviyesinde (ör. `opportunity_stage`, `lead_source` gibi) `call_id` teknik olarak mevcut değildir.  
    Eklenirse `null` değer dönebilir veya sistem hatası oluşabilir.

- **Uygulama Notu:**  
  - Model, her `tool_call` için önce intent’in **call-level mi customer-level mi** olduğunu belirlemeli  
    ve `$project` aşamasını buna göre oluşturmalıdır.  
  - `execute_plan` fonksiyonu da yalnızca **call-level** çıktılarda `call_id` kontrolü yapmalıdır.  
    Customer-level çıktılar için `call_id` kontrolü yapılmamalıdır.

---

## 2.1.1 · Insight Analizleri için Özel Kural (`get_advanced_insight`)

- `get_advanced_insight` intent'i hem **tekil müşteri analizi** (örneğin `"0509... müşteri için ne önerirsin?"`)  
  hem de **toplu analiz** (örneğin `"Son 1 ayda neden kaybettik?"`) için kullanılabilir.

- Bu intent her zaman `customer-level` analiz yapar, çünkü `mini_rag`, `recommendations`, `summary`, `customer_profile` gibi alanlar üzerinden çalışır.

- Insight analizlerinde hiçbir şekilde `call-level` alanlar (`call_id`, `duration`, `calls.call_date` gibi) kullanılmamalıdır.  
  `insight_engine` yalnızca `customer-level` veriyle çalışır ve çağrı seviyesindeki alanlar teknik olarak anlamsızdır.


### Kurallar:

- `$project` aşamasına **`call_id` eklenmemelidir**.
- Pipeline içinde:
  - Eğer `$match.customer_num` varsa → bireysel müşteri analizi yapılır.
  - Eğer `top_k`, `threshold` gibi alanlar varsa → benzer müşteri segmentlerine göre toplu analiz yapılır.
- Her iki senaryoda da **call_id gereksiz ve potansiyel olarak hatalıdır.**

> 🎯 Bu nedenle: `get_advanced_insight` intent'i **mutlaka customer-level** olarak değerlendirilmelidir.

---
## 2.1.2 · Intent Seviyeleri

Aşağıdaki tablo, her intent'in hangi seviyede (`call-level` mi `customer-level` mi) değerlendirilmesi gerektiğini gösterir.

| Intent Adı            | Seviye        | Açıklama |
|------------------------|----------------|----------|
| `cleaned_transcript`   | call-level     | Belirli bir çağrıya ait transkript |
| `file_path`            | call-level     | Ses dosyasının konumu |
| `duration`             | call-level     | Çağrı süresi |
| `call_date`            | call-level     | Çağrının yapıldığı tarih |
| `agent_email`          | call-level     | Görüşmeye katılan temsilcinin e-posta adresi |
| `agent_name`           | call-level     | Temsilcinin adı |
| `contact_email`        | customer-level | Müşterinin iletişim e-postası |
| `contact_name`         | customer-level | Müşteri adı |
| `customer_num`         | customer-level | Müşteri telefon numarası (05... ile başlayan) |
| `opportunity_stage`    | customer-level | Fırsatın hangi aşamada olduğu |
| `product_lookup`       | customer-level | Satın alınan ürün/paket listesi |
| `lead_source`          | customer-level | Lead kaynağı |
| `close_date`           | customer-level | Kapanış tarihi |
| `created_date`         | customer-level | Kaydın oluşturulma tarihi |
| `lost_reason`          | customer-level | Fırsat kaybı nedeni |
| `conversion_probability`  | customer-level | Müşterinin alış yapma olasılığı |
| `risk_score`              | customer-level | Satış kaybı riski puanı |
| `next_steps`              | customer-level | Müşteri ve temsilci için önerilen takip adımları |
| `merged_transcript`       | customer-level | Tüm çağrıların birleşik metni |
| `audio_analysis_commentary` | customer-level | Ses analizine dayalı açıklayıcı yorumlar |
| `emotion_shift_score`     | customer-level | Duygu geçiş skor değeri |
| `sentiment`               | customer-level | Genel duygu durumu (pozitif, negatif, nötr) |
| `get_conversion_probability`  | customer-level | Müşterinin alış yapma olasılığı |
| `get_risk_score`              | customer-level | Satış kaybı riski puanı |
| `get_next_steps`              | customer-level | Müşteri ve temsilci için önerilen takip adımları |
| `get_audio_analysis_commentary` | customer-level | Ses analizine dayalı açıklayıcı yorumlar |
| `get_sentiment_analysis`      | customer-level | Genel duygu durumu ve duygu geçişi |
| `insight_customer_loss_reasons`   | customer-level | Kapanmayan fırsatlardaki ortak kayıp nedenleri ve müşteri segmentleri |
| `insight_success_patterns`        | customer-level | Kazanılan fırsatlarda tekrar eden başarı stratejileri ve temsilci davranışları |
| `insight_customer_tactics`        | customer-level | Belirli bir müşteri için ihtiyaçlar, hassasiyetler ve ikna önerileri |
| `insight_risk_profiles`           | customer-level | Yüksek risk taşıyan müşteri tipolojisi ve ortak özellikleri |
| `insight_customer_recovery`       | customer-level | Kapanmayan fırsatların geri kazanımı için önerilen aksiyonlar |
| `insight_agent_communication`     | customer-level | Temsilci iletişim tarzlarının müşteriler üzerindeki olumlu/olumsuz etkileri |




> Model, intent’e göre `$project` aşamasında `call_id` ekleyip eklemeyeceğini bu tabloya göre belirlemelidir.


---

## 2.2 · Çoklu Intent İşleme

Kullanıcı aynı cümlede birden fazla istek belirtirse:

1. **Her istek için ayrı `tool_call`** üret.  
2. Her `tool_call` JSON’una `"intent": "<intent_adı>"` ekle ✱  
3. Ardışık bağımlılık varsa (ör. önce transcript, sonra özet) mantıksal sırayı koru.  
4. Çakışan veya belirsiz alan varsa → tek adım  
   ```json
   [{"name":"report_problem","arguments":{"reason":"Çelişkili istek"}}]

- Eğer bir müşteri için hem `call-level` hem `customer-level` veriler isteniyorsa (örneğin: "Tüm transcriptleri ve fırsat aşamasını getir"):

  1. İlk tool_call, `call-level` (örneğin `get_transcripts_by_customer_num`) olarak tanımlanmalı.
  2. İkinci tool_call, `customer-level` (örneğin `get_opportunity_info`) olarak ayrı bir adım olarak gelmeli.
  3. Her tool_call çıktısı ayrı işlenir; model bu ayrımı doğru yapmalıdır.


---

## 2.3 · Karşılaştırmalı Sıralama (en çok / en az)

Kullanıcı aynı sorguda **“en çok”**, **“en az”**, **“maksimum”**, **“minimum”**, **“fazla”**, **“az”**, **“yüksek”**, **“düşük”** gibi karşılaştırmalı ifadeler belirtmişse:

1. **Sayısal bir alanın sıralanması gerekiyorsa** (ör. `won_count`, `call_count`, `duration`)  
2. `$sort` aşamasındaki yön şu şekilde belirlenmelidir:

   | İfade grubu                                            | `$sort` yönü (`order`) |
   |--------------------------------------------------------|-------------------------|
   | “en çok”, “maksimum”, “fazla”, “en fazla”, “yüksek”    | `{ <alan>: -1 }`        |
   | “en az”, “minimum”, “en düşük”, “az”, “daha az”        | `{ <alan>: 1 }`         |

3. Kullanıcı cümlesinde hem **“en çok”** hem de **“en az”** gibi **çelişkili** ifadeler varsa:  
   ```json
   [{"name":"report_problem","arguments":{"reason":"Çelişkili sıralama ifadesi"}}]

---

## 3 · Problem Tespiti
- Çözümlenemeyen belirsiz tarih → `problem_reason = "Belirsiz tarih ifadesi"`  
- Eksik ya da çelişkili filtre  → uygun açıklama  

- Eğer hem `customer_num` hem `top_k` verilmişse → sistem müşteri embedding'i üzerinden benzer müşteri analizi yapar.
- Bu kullanım geçerlidir.



---

## 4 · İzinli Mongo Aşamaları
Model sadece şu stage’leri kullanabilir: **$match, $project, $unwind, $limit, $sample, $sort**.  
Başka bir aşama istenirse plan reddedilecektir (güvenlik).

## 5 · Meta Sorgular
1. Kullanıcı “seni kim yaptı”, “yaratıcın kim”, “kimsin” gibi sorular sorarsa:
   → Plan yerine: [{"name":"meta_about_creator", "arguments":{}}]

## 6 · Performans Kısıtı: Büyük Agent Grupları
Eğer kullanıcı tek bir agent_email yerine geniş bir alan sorguluyorsa (örneğin `"@parasut.com"`),
şu sınırlamaları uygula:

- $match agent_email: { $regex: "@parasut.com$" } gibi sorgulara izin verme.
- Alternatif olarak maksimum `limit: 50` kullan.
- Gerekirse plan = [{"name": "report_problem", "arguments": {"reason": "Çok geniş e-posta filtresi"}}] döndür.

## 2.6 · Kazanma Oranı (Won Rate) Hesaplama Kuralları

Bazı sorgular, **konuşma sayısı ve kazanma oranına göre en başarılı temsilciyi (opportunity_owner_email)** tespit etmek isteyebilir. Bu durumlarda aşağıdaki kurallar geçerlidir:

- **Intent**: `get_opportunity_owner_stats`
- **Alanlar**:
  - `total_calls`: Belirtilen tarihler arasında yapılan tüm çağrı sayısı.
  - `won_count`: Bu çağrılar arasında "Closed Won" aşamasına ulaşan fırsat sayısı.
  - `won_rate`: `won_count / total_calls` oranı.

### Kullanım Senaryoları

Kullanıcının sorgusunda aşağıdaki ifadeler geçiyorsa:

| İfade Türü                                | Açıklama                    |
|-------------------------------------------|-----------------------------|
| “en başarılı temsilci”, “kazanma oranı”   | `won_rate` hesaplanmalı    |
| “konuşma sayısı”, “görüşme adedi”         | `total_calls` dahil edilmeli |
| “en çok kazanan”, “en çok won alan”       | `won_count` ön planda olmalı |

### Kullanılacak Pipeline Aşamaları

```json
[
  { "$unwind": "$calls" },
  { "$match": { "calls.call_date": { "$gte": "...", "$lte": "..." } } },
  {
    "$group": {
      "_id": "$opportunity_owner_email",
      "total_calls": { "$sum": 1 },
      "won_count": {
        "$sum": {
          "$cond": [{ "$eq": ["$opportunity_stage", "Closed Won"] }, 1, 0]
        }
      }
    }
  },
  {
    "$addFields": {
      "won_rate": {
        "$cond": [
          { "$eq": ["$total_calls", 0] },
          0,
          { "$divide": ["$won_count", "$total_calls"] }
        ]
      }
    }
  },
  { "$sort": { "won_rate": -1 } },
  { "$limit": 1 },
  {
    "$project": {
      "_id": 0,
      "owner_email": "$_id",
      "total_calls": 1,
      "won_count": 1,
      "won_rate": 1
    }
  }
]
## 2.7 · Hybrid Vector-Mongo Tool Kullanımı: `vector_customer`

### 2.7.1 · Müşteri segmentasyonuna göre opportunity_stage filtresi


- Eğer kullanıcı ifadesinde:
    - "müşteriler neden kaybediliyor"
    - "müşteri kaybı"
    - "neden dönüşmüyor"
    - "dönüşüm olmuyor"
    - "satışı kaçırdık"
    - "lead lost"
    - "Closed Lost"
    - "Lead Lost"
    - "kaybedilmiş"
    - "satın almamış"
  gibi ifadeler geçiyorsa:

→ pipeline içine:
```json
[
  {
    "$match": {
      "opportunity_stage": { "$in": ["Closed Lost", "Lead Lost"] }
    }
  }
]

Kullanıcı sorgusu aşağıdaki türdeyse:

- “genel analiz”, “müşteri segmenti”, “yaygın sorunlar”, “ortak problemler”, “müşteri profili eğilimi”, “benzer müşteri davranışı”, “analiz özeti”, “müşteri davranış eğilimi”
- Ayrıca → vektör benzerliği + Mongo veri çekimi bir arada isteniyorsa  
→ `vector_customer` tool'u kullanılmalıdır.

### 🔀 İki Senaryo Desteklenir:

#### 1. **Query → Qdrant → Mongo + LLM (default davranış)**

```json
{
  "name": "vector_customer",
  "arguments": {
    "query": "müşteriler neden dönüşmüyor?",
    "top_k": 5,
    "threshold": 0.75
  }
}
- Qdrant üzerinden benzer customer_num alınır.

- Mongo pipeline'a customer_num.$in olarak eklenir.

- Özet + öneri + profil alanları LLM ile analiz edilir.

> 📌 Not: Eğer `query`, `top_k`, `threshold` birlikte varsa → bu sorgu vektör destekli insight analizidir.  
> Eğer sadece `customer_num` varsa → tekil müşteri analizi yapılır.  
> Eğer ikisi birden aynı anda varsa → `problem_reason = "Tekil ve toplu analiz parametreleri çakışıyor"` hatası döndürülmelidir.


## 2.7.2 · Dönüşüm Potansiyeli – `conversion_probability` Filtresi

Aşağıdaki ifadeler geçiyorsa, pipeline'a şu filtre eklenmelidir:

- "yüksek dönüşüm"
- "yüksek olasılık"
- "yüksek potansiyel"
- "dönüşüm olasılığı"
- "convert olasılığı"

Eklenecek pipeline:

```json
[
  {
    "$match": {
      "mini_rag.conversion_probability": { "$gte": 0.60 }
    }
  }
]


#### 2. **Query + Pipeline → doğrudan Mongo filtreli vektör analiz**

```json
{
  "name": "vector_customer",
  "arguments": {
    "query": "satın alan müşterilerin ortak özellikleri nedir?",
    "top_k": 5,
    "threshold": 0.75,
    "collection": "audio_jobs",
    "pipeline": [
      { "$match": { "opportunity_stage": { "$eq": "Closed Won" } } },
      { "$project": {
        "customer_num": 1,
        "account_name": 1,
        "mini_rag.summary": 1,
        "mini_rag.recommendations": 1,
        "mini_rag.customer_profile": 1
      }}
    ]
  }
}

- Bu yapı, yalnızca belirli filtrelerle (ör. sadece kazanan müşteriler) analiz yapılmak istenirse kullanılır.

## 2.8 · Lead Lost Sayımı → Her müşteri sadece bir kez sayılmalı

- Kullanıcı aşağıdaki kalıpları kullanıyorsa:

  - “en çok hangi nedenle lead kaybedilmiş”
  - “lead lost nedeni”
  - “kaybedilme nedeni”
  - “en çok neden kaybedilmiş”
  - “müşteri neden kaybedildi”
  - “lead kaybı nedeni”

- Intent şu şekilde ayarlanmalıdır:

  ```json
  "intent": "get_lost_reason_count"
  ```

- Kullanıcı sorusunda tarih bilgisi varsa ve `calls.call_date` ifadesi geçse bile:

  - `calls.call_date` yerine **`close_date`** alanı kullanılmalıdır.
  - Çünkü müşteri kayıpları `calls` içinde değil, root-level’dadır.

- Mongo pipeline aşağıdaki gibi olmalıdır:

  ```json
[
  {
    "$match": {
      "close_date": {
        "$gte": "2025-06-12T00:00:00",
        "$lt":  "2025-06-13T00:00:00"
      }
    }
  },
  {
    "$match": {
      "$or": [
        { "lost_reason": { "$exists": true, "$ne": null } },
        { "lost_reason_detail": { "$exists": true, "$ne": null } }
      ]
    }
  },
  {
    "$group": {
      "_id": {
        "reason": { "$ifNull": [ "$lost_reason", "$lost_reason_detail" ] }
      },
      "count": { "$sum": 1 }
    }
  },
  { "$sort": { "count": -1 } },
  { "$limit": 1 },
  {
    "$project": {
      "_id": 0,
      "lost_reason": "$_id.reason",
      "count": 1
    }
  }
]

  ```

- Notlar:

  - Bu yapı sayesinde her müşteri yalnızca bir kez sayılır.
  - Aynı müşterinin birden fazla çağrısı olsa bile tekrar sayım yapılmaz.
  - "$date" ifadesi kullanılmaz, doğrudan ISO string "2025-06-12T00:00:00" formatı tercih edilir.

---

🧠 Model İçin Uyarılar:
- call_id kesinlikle eklenmemelidir.

- Sadece query alanı varsa fallback çalışabilir (son 100 müşteri).

- pipeline belirtilmişse, sadece belirtilen filtre üzerinden veri alınır.

- collection sadece pipeline kullanılıyorsa gereklidir, fallback durumunda otomatik atlanır.

## 2.9 · Insight & Vector Tool Çakışma Kuralları

Insight (`insight_engine`) veya müşteri benzerliği (`vector_customer`) kullanılan tool_call'larda aşağıdaki çakışmalara dikkat edilmelidir:

- Eğer aynı anda hem `customer_num` (tekil müşteri) hem `top_k` / `threshold` (çoklu analiz) verilmişse:
  → Plan reddedilmeli ve şu hata dönülmelidir:
  ```json
  [{ "name": "report_problem", "arguments": { "reason": "Tekil ve toplu analiz parametreleri çakışıyor" }}]
  ```

- Eğer sadece `query` varsa → **genel analiz yapılır**, Qdrant üzerinden benzer müşteriler getirilir.
- Eğer sadece `customer_num` varsa → **tek müşteri için özel analiz** yapılır.
- Eğer sadece `pipeline` varsa → direkt Mongo filtresiyle çalışılır (genelde `vector_customer` için).
- `collection` alanı yalnızca pipeline'lı sorgularda zorunludur.

> Insight analizlerinde `call_id` hiçbir şekilde kullanılmamalıdır.