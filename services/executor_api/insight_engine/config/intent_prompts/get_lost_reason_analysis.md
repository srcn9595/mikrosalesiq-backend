---
# AMAÇ
# Bu analiz, son 1 ayda kaybedilen veya kapanmayan fırsatlarda tekrar eden temsilci ve süreç hatalarını, iletişim kopukluklarını, müşteri temasındaki eksikleri ve temsilci performansında öne çıkan örüntüleri bulmak için kullanılır.
# Yöneticinin işine gerçekten yarayacak, **kanıtlı, gerçek, özgün ve detaylı** satış analiz raporu hazırlanacaktır.
# Aşağıdaki kurallara harfiyen uyulacaktır:
#
# - Çıktı kesinlikle **aşağıdaki JSON şeması** ile birebir uyumlu ve alan bazında gelmeli.
# - Her alan **çok satırlı, anlamlı, veriyle ve müşteri sözüyle destekli** açıklamalar içermeli.
# - “Tablo” alanları array olarak, ama içerik *tabloya gerek bırakmayacak netlikte* ve örnekli olmalı.
# - Klişe, yüzeysel veya tekrar eden cümleler YASAK! Hiçbir alan kopya/yapay cümle içermesin.
# - Tüm müşteri/temsilci isimleri, e-posta ve telefonlar **M*** şeklinde maskelecek.
# - Fiyat sadece ana neden ise açık yazılacak.
# - **Boş/eksik veri varsa** alan boş bırakılacak ("" veya []) - asla uydurma doldurma!
# - Alanların sırası, isimleri değiştirilmeyecek, **ekstra field eklenmeyecek/silinmeyecek.**
# - **Veri yoksa:** Sadece `{ "message": "Yeterli kayıp kaydı bulunamadı." }`
---

### JSON Çıktı Şeması

```json
{
  "summary": { "headline": "", "customer_quote": "" },
  "fail_patterns": [
    { "pattern": "", "percent": 0, "customer_quote": "" }
  ],
  "agent_analysis": [],
  "director_alerts": [],
  "actions": [],
  "winback_advice": ""
}
---
### Alan Açıklamaları

- **summary.headline:** Şok edici veri ve müşteri yorumu içeren özet.  
  *Örnek: “Son 1 ayda 14 fırsatın 9’u, demo sonrası hiç iletişim kurulmadığı için kaybedildi.”*

- **summary.customer_quote:** En iyi “kanıt cümlesi”, doğrudan müşteri ağzından, maskele.  
  *Örnek: “M***: Demo bitti, kimse aramadı, başka firmayla çalışmaya başladık.”*

- **fail_patterns:** En az 3, en fazla 5, her biri `{pattern, percent, customer_quote}`; müşteri örnekleri maskele.  
  *Örnek: `{ "pattern": "Demo sonrası iletişimsizlik", "percent": 48, "customer_quote": "M***: Demo sonrası kimse aramadı, ilgisiz kaldım." }`*

- **agent_analysis:** Temsilci davranışında örüntü ve oranla açıklama.  
  *Örnek: “Ses tonu düşük olanlarda kayıp %60.”*

- **director_alerts:** Net ve oranlı alarm.  
  *Örnek: “Demo sonrası 48 saat içinde %0 tekrar iletişim: En büyük kayıp nedeni!”*

- **actions:** Somut, doğrudan aksiyon.  
  *Örnek: “Demo sonrası 24 saatte temas zorunlu, otomatik hatırlatıcı kuralı eklenmeli.”*

- **winback_advice:** Geri kazanım için doğrudan uygulanabilir taktik.  
  *Örnek: “Son 1 ayda iletişimi kopan tüm müşterilere özel geri arama planı hazırlanmalı.”*

- **Veri yoksa:**  
  `{ "message": "Yeterli kayıp kaydı bulunamadı." }`
{
  "summary": {
    "headline": "Son 1 ayda 14 fırsatın 9’u, demo sonrası hiç iletişim kurulmadığı için kaybedildi.",
    "customer_quote": "M***: 'Demo bitti, kimse aramadı, başka firmayla çalışmaya başladık.'"
  },
  "fail_patterns": [
    {
      "pattern": "Demo sonrası iletişimsizlik",
      "percent": 48,
      "customer_quote": "M***: Demo sonrası kimse aramadı, ilgisiz kaldım."
    },
    {
      "pattern": "Soruya geç yanıt veya hiç yanıt verilmemesi",
      "percent": 29,
      "customer_quote": "M***: Mail attım, 3 gün sonra döndüler, başka firma daha hızlıydı."
    },
    {
      "pattern": "Teklifte netlik eksikliği",
      "percent": 16,
      "customer_quote": "M***: Cevap alamayınca başka firmaya gittim."
    },
    {
      "pattern": "Fiyat",
      "percent": 7,
      "customer_quote": "M***: Fiyat yüksek, ama asıl sorun kimse açıklama yapmadı."
    }
  ],
  "agent_analysis": [
    "Ses tonu düşük ve güven vermeyen temsilcilerde kayıp oranı %60.",
    "Son 10 görüşmede, müşteri konuşma süresi toplamın %70’i; temsilci yönlendirme yapmamış."
  ],
  "director_alerts": [
    "Demo sonrası 48 saat içinde %0 tekrar iletişim: En büyük kayıp nedeni!",
    "Müşteri geri bildirimi olmadan 7/14 fırsatta süreç kendiliğinden sonlandı.",
    "Her 4 kayıptan 1’i 'kararsız kaldım, sorum yanıtsız' dedi; Takip sistemi yok."
  ],
  "actions": [
    "Demo sonrası her müşteriyle 24 saat içinde temas zorunlu; otomatik hatırlatıcı kuralı eklenmeli.",
    "Müşteri sorusu veya teklif geldiğinde 1 iş günü içinde dönüş yapılacak; izleme sistemi kurulmalı.",
    "Son temas tarihi kaydedilecek, 2 günden uzun beklemeye 'kırmızı alarm' atanacak."
  ],
  "winback_advice": "Son 1 ayda iletişimi kopan tüm müşterilere özel geri arama planı hazırlanmalı; her biri için gerekirse özelleştirilmiş teklif sunulmalı."
}
---

### TL;DR:

- Çıktı **her zaman aşağıdaki JSON şemasına** göre, alan bazında ve ek/yüzeysel alan eklemeden gelmeli.
- Tüm açıklamalar ve örnekler, insan gibi, **çok satırlı, bağlamsal, kanıta dayalı** şekilde üretilmeli.
- Tablo gerektiren yerlerde array yapısı kullanılacak ama içerik yine net, anlamlı ve açıklayıcı olacak.
- Müşteri ve temsilci isimleri **M*** şeklinde maskelecek.
- Klişe veya genel-geçer cümleler asla olmayacak; **sadece veriden çıkan ve müşteri ağzından** içerik üretilecek.
- Eksik veri varsa ilgili alanlar boş bırakılacak ("" veya []), asla uydurma doldurma yapılmayacak.
- **Veri yoksa:** `{ "message": "Yeterli kayıp kaydı bulunamadı." }` olarak dönecek.
- Alan isimleri, sırası ve JSON yapısı **asla değiştirilmeyecek**.

---