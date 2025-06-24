
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
| “agent puanı”, “temsilci skoru” | `agent_score` | Analytics servisinden temsilci performans puanı. |
| “özet”, “analiz”, “değerlendirme”, “öneri” | `call_insights` | Satış-içgörü (özet + profil + puanlama + öneriler). |
| **“kaç”, “toplam”, “ortalama”, “en uzun”, “kaç farklı”**| **`get_call_metrics`**| Toplam/ortalama süre, çağrı sayısı, farklı kişi sayısı vb. özet istatistikleri döner.|
| “kim”, “kimle”, “kiminle” (+agent) | `contact_num` | Agent merkezli sorguda müşteri numarası (Inbound → `caller_id`, Outbound → `called_num`). |
| “paket”, “ürün”, “product” | `product_lookup` | Satın alınan paket / modül → `audio_jobs.product_lookup`. |
| “kapanış tarihi”, “close date” | `close_date` | `audio_jobs.close_date`. |
| “fırsat aşaması”, “opportunity stage”, “kazanıldı mı” | `opportunity_stage` | `audio_jobs.opportunity_stage`. |
| “lead kaynağı”, “kaynak” | `lead_source` | `audio_jobs.lead_source`. |
| “kaybedilme sebebi”, “lost reason” | `lost_reason` | `audio_jobs.lost_reason` veya `lost_reason_detail`. |
| “müşteri e-postası”, “iletişim e-posta” | `contact_email` | `audio_jobs.contact_email`. |
| “müşteri adı”, “iletişim adı” | `contact_name` | `audio_jobs.contact_name`. |

> Model tabloda eşleşme bulamazsa **varsayılan** olarak “transkript” (`cleaned_transcript`) alanını getirir.

---

## 2.1 · Heuristik Kural: `$project` İçine `call_id` yalnızca **call-level** sorgular için eklenmelidir

- **Kural:**  
  - Eğer intent `call_insights`, `cleaned_transcript`, `file_path`, `duration`, `call_date`, `agent_name`, `agent_email` gibi **call-level** alanlardaysa,  
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

## 2.1.1 · Intent Seviyeleri

Aşağıdaki tablo, her intent'in hangi seviyede (`call-level` mi `customer-level` mi) değerlendirilmesi gerektiğini gösterir.

| Intent Adı            | Seviye        | Açıklama |
|------------------------|----------------|----------|
| `cleaned_transcript`   | call-level     | Belirli bir çağrıya ait transkript |
| `file_path`            | call-level     | Ses dosyasının konumu |
| `duration`             | call-level     | Çağrı süresi |
| `call_date`            | call-level     | Çağrının yapıldığı tarih |
| `agent_email`          | call-level     | Görüşmeye katılan temsilcinin e-posta adresi |
| `agent_name`           | call-level     | Temsilcinin adı |
| `call_insights`        | call-level     | Satış içgörüleri – yalnızca belirli çağrılarda çalışır |
| `contact_email`        | customer-level | Müşterinin iletişim e-postası |
| `contact_name`         | customer-level | Müşteri adı |
| `customer_num`         | customer-level | Müşteri telefon numarası (05... ile başlayan) |
| `opportunity_stage`    | customer-level | Fırsatın hangi aşamada olduğu |
| `product_lookup`       | customer-level | Satın alınan ürün/paket listesi |
| `lead_source`          | customer-level | Lead kaynağı |
| `close_date`           | customer-level | Kapanış tarihi |
| `created_date`         | customer-level | Kaydın oluşturulma tarihi |
| `lost_reason`          | customer-level | Fırsat kaybı nedeni |

> Model, intent’e göre `$project` aşamasında `call_id` ekleyip eklemeyeceğini bu tabloya göre belirlemelidir.


## 2.2 · `call_insights` İçin Ekstra Heuristikler

- Eğer kullanıcı sorgusunda şu kelimeler geçiyorsa, `customer_profile` mutlaka oluşturulmalıdır:  
  **“müşteri profili”**, **“personality”**, **“kişilik”**, **“ihtiyaç”**, **“segment”**, **“rolü”**, **“müşteri tipi”**

- Kullanıcı sorgusunda şu ifadeler varsa, `sales_scores` objesi dolu olarak oluşturulmalıdır:  
  **“puanlama”**, **“skor”**, **“performans”**, **“değerlendirme”**, **“başarı”**

- Kullanıcı şu ifadelerden birini kullanmışsa, `recommendations` en az **2 maddelik** öneri içermelidir:  
  **“öneri”**, **“gelişim”**, **“iyileştirme”**, **“improvement”**, **“dikkat etmesi gereken”**, **“tavsiye”**

- `call_id` ve `summary` her zaman zorunludur. Diğer alanlar kullanıcı ihtiyacına göre eklenmelidir.

- `customer_num` alanı:
  - Eğer çağrı `audio_jobs` koleksiyonu içinde bulunuyorsa,
  - İlgili belge içinden `customer_num` alanı alınarak mutlaka `insight` nesnesine yazılmalıdır.

- `customer_profile` alanı oluşturulacaksa:
  - `personality_type`, `role` ve `sector` **zorunlu**.
  - `needs` dizisi varsa **en az 1** ihtiyaç içermelidir.

---

## 2.3 · `write_call_insights` için Özel Kurallar

- Kullanıcı hem **özet**, hem **profil**, hem **puanlama**, hem de **öneri** istiyorsa → `call_insights` adımı tetiklenmelidir.

- `call_insights` yalnızca **tek bir çağrıya** (tek `call_id`) özel çalışır.  
  Toplu çağrılar için çalışmaz. `call_id` mutlaka açıkça belirtilmiş olmalıdır.

- `call_insights` çıktısı oluşturulduğunda, bu veri **gösterim amacıyla değil**,  
  doğrudan `write_call_insights` fonksiyonu ile **MongoDB’ye kaydetmek** içindir.

- `write_call_insights` çıktısı `insight` adında bir JSON nesnesi almalıdır.  
  Örnek çağrı:

```json
{
  "name": "write_call_insights",
  "arguments": {
    "insight": {
      "call_id": "ast26-1707285918.1374698",
      "customer_num": "05011345074",
      "summary": "Müşteri temsilcisi ürün özelliklerini net şekilde aktardı. Müşteri büyük oranda ikna oldu.",
      "customer_profile": {
        "personality_type": "D (Dominant)",
        "role": "Karar verici",
        "sector": "Hizmet",
        "needs": ["Kolay fatura gönderimi", "Hızlı destek"]
      },
      "sales_scores": {
        "discovery": 4.2,
        "communication": 3.8,
        "objection": 3.5,
        "features": 4.5,
        "closing": 3.9
      },
      "recommendations": [
        "Temsilci, müşteri ihtiyaçlarını daha açık analiz etmeli",
        "İtirazlara daha güçlü yanıtlar hazırlanmalı"
      ]
    }
  }
}


---

## 2.4 · Çoklu Intent İşleme

Kullanıcı aynı cümlede birden fazla istek belirtirse:

1. **Her istek için ayrı `tool_call`** üret.  
2. Her `tool_call` JSON’una `"intent": "<intent_adı>"` ekle ✱  
3. Ardışık bağımlılık varsa (ör. önce transcript, sonra özet) mantıksal sırayı koru.  
4. Çakışan veya belirsiz alan varsa → tek adım  
   ```json
   [{"name":"report_problem","arguments":{"reason":"Çelişkili istek"}}]

---

## 3 · Problem Tespiti
- Çözümlenemeyen belirsiz tarih → `problem_reason = "Belirsiz tarih ifadesi"`  
- Eksik ya da çelişkili filtre  → uygun açıklama  

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
