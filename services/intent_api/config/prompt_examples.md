# prompt_examples.md

# 1 — Call bazlı Genel Analiz Özeti
- user: "call id si ast26-1707285918.1374698 olan konuşmanın genel analizini getir"
  tool_call:
    name: call_insights
    arguments:
      call_id: "ast26-1707285918.1374698"

# 2 — Müşteri bazlı Genel Analiz Özeti
- user: "05011345074 numaralı müşterinin genel analizini getir"
  tool_call:
    name: get_mini_rag_summary
    arguments:
      customer_num: "05011345074"

# 3 — Tek call_id
- user: "ast26-1707285918.1374698 transcriptini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_id: "ast26-1707285918.1374698"
        - $project:
            _id: 0
            call_id:    "$calls.call_id"
            call_date:  "$calls.call_date"
            transcript: "$calls.cleaned_transcript"

# 4 — Müşteri numarası + tek gün
- user: "05011345074 müşterisinin 29 Nisan 2024 görüşmelerini gönder"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05011345074"
            calls.call_date:
              $gte: "2024-04-29"
              $lte: "2024-04-29"
        - $project:
            _id: 0
            call_id:    "$calls.call_id"
            transcript: "$calls.cleaned_transcript"

# 5 — Temsilci e-mail + süre filtresi
- user: "esin.engin@parasut.com'un 1 dakikadan uzun son 3 görüşmesini bul"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.agent_email: "esin.engin@parasut.com"
            calls.duration: { $gt: 60 }
        - $sort:
            calls.call_date: -1
        - $limit: 3
        - $project:
            _id:      0
            call_id:  "$calls.call_id"
            duration: "$calls.duration"
            transcript: "$calls.cleaned_transcript"

# 6 — Vektör arama
- user: "E-fatura kurulumu sorusu geçen kayıtları bul"
  tool_call:
    name: vector_search
    arguments:
      namespace: "parasut"
      query:     "e-fatura kurulumu"
      top_k:     5

# 7 — Müşteri numarasına göre tüm görüşmeler
- user: "05011345074 numaralı müşterinin görüşmelerini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05011345074"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            transcript: "$calls.cleaned_transcript"

# 8 — Call_id ve cleaned_transcript mevcutsa direkt getir
- user: "ast26-1714378983.2356434 çağrısının transkriptini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_id: "ast26-1714378983.2356434"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            call_date:  "$calls.call_date"
            transcript: "$calls.cleaned_transcript"

# 9 — Call_id için transcript olup olmadığına göre karar (executor karar verir)
- user: "ast26-1234567890 çağrısının transkriptini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_id: "ast26-1234567890"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            transcript: "$calls.cleaned_transcript"

# 10 — Customer_num’a göre önce aggregate, eksik varsa executor kuyruk kararını verir
- user: "05012345678 numaralı müşterinin transkriptlerini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05012345678"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            transcript: "$calls.cleaned_transcript"

# 11 — Bir call_id için agent bilgisi ve çağrı tarihi
- user: "ast26-1707285918.1374698 numaralı çağrıyı kim yapmış ve ne zaman?"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: call_records
      pipeline:
        - $match:
            call_id: "ast26-1707285918.1374698"
        - $project:
            _id:          0
            call_id:      "$call_id"
            call_date:    "$call_date"
            agent_email:  "$agent_email"
            agent_name:   "$agent_name"
            caller_id:    "$caller_id"
            called_num:   "$called_num"

# 12 — Müşteri numarasının en son görüşmesi ve temsilcisi
- user: "05011345074 en son kimle görüşmüş ve ne zaman?"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: call_records
      pipeline:
        - $match:
            $or:
              - caller_id: "05011345074"
              - called_num: "05011345074"
        - $sort:
            call_date: -1
        - $limit: 1
        - $project:
            _id:         0
            call_id:     "$call_id"
            call_date:   "$call_date"
            agent_email: "$agent_email"
            agent_name:  "$agent_name"

# 13 — Müşteri numarasının tüm temsilci trafiği
- user: "05011345074 hangi temsilcilerle görüşmüş?"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: call_records
      pipeline:
        - $match:
            $or:
              - caller_id: "05011345074"
              - called_num: "05011345074"
        - $project:
            _id:         0
            call_id:     "$call_id"
            agent_email: "$agent_email"
            agent_name:  "$agent_name"

# 14 — Sistemi kim geliştirdi?
- user: "Bu sistem seni kim yaptı?"
  tool_call:
    name: meta_about_creator
    arguments: {}

# 15 — Çağrı bazlı insight (özet, profil, öneri)
- user: "ast26-1707285918 çağrısının özetini, profilini ve önerilerini çıkart"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_id: "ast26-1707285918"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            call_date:  "$calls.call_date"
            transcript: "$calls.cleaned_transcript"

# 16 — Müşteri bazlı satış-insight raporu
- user: "05011345074 numaralı müşterinin satış-insight raporunu ver"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05011345074"
        - $project:
            _id:        0
            call_id:    "$calls.call_id"
            transcript: "$calls.cleaned_transcript"

# 17 — Çağrı bazlı Performans ve Özet Değerlendirmesi (call_insights)
- user: "ast26-1707285918 numaralı çağrının performans değerlendirmesini yap"
  tool_call:
    name: call_insights
    arguments:
      call_id: "ast26-1707285918"

- user: "ast26-1707285918 çağrısında temsilcinin güçlü ve zayıf yönlerini analiz et"
  tool_call:
    name: call_insights
    arguments:
      call_id: "ast26-1707285918"



# 18 — Çağrı bazlı insight üret ve MongoDB’ye kaydet
- user: "ast26-1707285918 çağrısı için analiz çıkar, müşteri profilini ve temsilci puanlarını kaydet"
  tool_call:
    name: write_call_insights
    arguments:
      insight:
        call_id: "ast26-1707285918"
        summary: "Müşteri temsilcisi, temel ürün bilgilerini açıkça anlattı. Müşteri bazı itirazlar getirdi ancak büyük ölçüde ikna edildi."
        customer_num: "05011345074"
        customer_profile:
          personality_type: "D (Dominant)"
          role: "Karar verici"
          sector: "Hizmet"
          needs: ["Kolay fatura gönderimi", "Hızlı destek"]
        sales_scores:
          discovery: 3.5
          communication: 4.0
          objection: 3.0
          features: 4.5
          closing: 3.2
        recommendations:
          - "Temsilci, müşteri ihtiyaçlarını daha iyi analiz etmeli"
          - "İtirazlara daha güçlü yanıtlar hazırlanmalı"

# 19 — Müşteri numarası, mixed durum (cleaned yok → senkron temizle / kuyruğa at)
- user: "05320122474 numaralı müşterinin tüm transkriptlerini getir"
  tool_call:
    name: mongo_aggregate
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05320122474"
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            transcript: "$calls.transcript"
            cleaned_transcript: "$calls.cleaned_transcript"

# 20. — Birden çok müşterinin genel analizini getir
- user: "05000000001 ve 05000000002 müşterilerinin genel analizini getir"
  tool_call:
    name: get_mini_rag_summary
    arguments:
      customer_nums: ["05000000001", "05000000002"]

# (LLM, eğer dönen listede transcript boş olan call_id’ler varsa
#  otomatik olarak aşağıdakini de çağırır)
- user: "Eksik transkriptler için enqueue et"
  tool_call:
    name: enqueue_transcription_job
    arguments:
      call_ids: ["ast26-…", "ast26-…", …]



