# prompt_examples.md  ·  2025-06 rev-01
# ────────────────────────────────────────────────────────────────
# NOT: Her örnek → tek bir “ideal” tool_call gösterir.
#     {name, arguments, intent} alanları bire bir manifest ile eşleşir.
# ────────────────────────────────────────────────────────────────

# 1 — CALL ANALYSIS (tek call_id → call_insights)
- user: "ast26-1707285918.1374698 çağrısının satış performansını analiz et"
  tool_call:
    name: call_insights
    intent: get_call_analysis
    arguments:
      call_id: "ast26-1707285918.1374698"

# 2 — CUSTOMER OVERVIEW (tek müşteri → mini-rag)
- user: "05011345074 müşterisinin genel analizini ver"
  tool_call:
    name: get_mini_rag_summary
    intent: get_customer_overview
    arguments:
      customer_num: "05011345074"

# 3 — TRANSCRIPT BY CALL_ID
- user: "ast26-1707285918.1374698 transcriptini göster"
  tool_call:
    name: mongo_aggregate
    intent: get_transcript_by_call_id
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match: { calls.call_id: "ast26-1707285918.1374698" }
        - $project: { _id: 0, call_id: "$calls.call_id", transcript: "$calls.cleaned_transcript" }

# 4 — TRANSCRIPTS BY CUSTOMER & DATE RANGE
- user: "05011345074 numarasının 29 Nisan 2024’teki görüşmelerini dök"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_by_customer_num
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            customer_num: "05011345074"
            calls.call_date: { $gte: "2024-04-29", $lte: "2024-04-29" }
        - $project: { _id: 0, call_id: "$calls.call_id", transcript: "$calls.cleaned_transcript" }

# 5 — AGENT + DURATION FILTER
- user: "esin.engin@parasut.com’un 1 dk’dan uzun son 3 çağrısını getir"
  tool_call:
    name: mongo_aggregate
    intent: get_call_dates
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.agent_email: "esin.engin@parasut.com"
            calls.duration: { $gt: 60 }
        - $sort: { calls.call_date: -1 }
        - $limit: 3
        - $project: { _id: 0, call_id: "$calls.call_id", call_date: "$calls.call_date" }

# 6 — VECTOR SEARCH (semantik)
- user: "E-fatura kurulumu geçen kayıtları bul"
  tool_call:
    name: vector_search
    intent: semantic_search
    arguments:
      namespace: "parasut"
      query: "e-fatura kurulumu"
      top_k: 5

# 7 — LAST AGENT / CALL DATE
- user: "05445118257 en son kimle görüşmüş ve ne zaman?"
  tool_call:
    name: mongo_aggregate
    intent: get_last_call
    arguments:
      collection: audio_jobs
      pipeline:
        - $match:  { customer_num: "05445118257" }
        - $unwind: "$calls"
        - $sort:   { "calls.call_date": -1 }
        - $limit:  1
        - $project:
            _id:          0
            call_id:      "$calls.call_id"
            call_date:    "$calls.call_date"
            agent_email:  "$calls.agent_email"
            agent_name:   "$calls.agent_name"
            customer_num: "$customer_num"


# 8 — MULTI-INTENT: transcript + overview
- user: "05320122474 numarasının tüm transcriptlerini ver, sonra genel özetini çıkart"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_by_customer_num
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match: { customer_num: "05320122474" }
        - $project: { _id: 0, call_id: "$calls.call_id", transcript: "$calls.cleaned_transcript" }
- tool_call:
    name: get_mini_rag_summary
    intent: get_customer_overview
    arguments:
      customer_num: "05320122474"

# 9 — ENQUEUE MISSING TRANSCRIPTS (executor kararına bırak)
- user: "ast26-XYZ çağrısının transkripti yoksa sıraya al"
  tool_call:
    name: enqueue_transcription_job
    intent: enqueue_transcription_job
    arguments:
      call_ids: ["ast26-XYZ"]

# 10 — META
- user: "Seni kim geliştirdi?"
  tool_call:
    name: meta_about_creator
    intent: meta_about_creator
    arguments: {}

# 11 — RELATIVE DATE (“dün”)
- user: "Dünün konuşma kayıtlarını getir"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_by_customer_num
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "{today-1d}"
              $lte: "{today-1d}"
        - $project: { _id:0, call_id:"$calls.call_id",
                             transcript:"$calls.cleaned_transcript" }

# 12 — EXPLICIT RANGE
- user: "12 Haziran 2024 ile 12 Haziran 2025 arasındaki kayıtları getir"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_by_customer_num
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "2024-06-12"
              $lte: "2025-06-12"
        - $project: { _id:0, call_id:"$calls.call_id", transcript:"$calls.cleaned_transcript" }

# 13 — RANDOM N CLEANED TRANSCRIPTS
- user: "Rastgele 5 transcript göster"
  tool_call:
    name: mongo_aggregate
    intent: get_random_transcripts
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:   { calls.status: "cleaned" }     # sadece temizler
        - $sample:  { size: 5 }                     # rastgele 5
        - $project: { _id:0, call_id:"$calls.call_id",
                             transcript:"$calls.cleaned_transcript" }

# 14 — AGENT’S CONTACTS (son 2 ay, inbound + outbound)
- user: "arda.eksioglu@parasut.com son 2 ayda kimlerle görüşmüş?"
  tool_call:
    name: mongo_aggregate
    intent: get_call_dates
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.agent_email: "arda.eksioglu@parasut.com"
            calls.call_date:   { $gte: "{today-2m}" }
        - $project:
            _id:          0
            call_id:      "$calls.call_id"
            customer_num: "$customer_num"
            call_date:    "$calls.call_date"
            agent_email:  "$calls.agent_email"
            agent_name:   "$calls.agent_name"



# 15 — RANDOM N TRANSCRIPTS + AGENT
- user: "Bana mevcutta var olan 5 random transcript getir, agent bilgisi de olsun"
  tool_call:
    name: mongo_aggregate
    intent: get_random_transcripts
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:  { calls.status: "cleaned" }
        - $sample: { size: 5 }
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            customer_num:"$customer_num"
            agent_email: "$calls.agent_email"
            agent_name: "$calls.agent_name"
            transcript: "$calls.cleaned_transcript"

# 16 — OPPORTUNITY STAGE (tek müşteri)
- user: "05326375292 fırsat aşaması ne?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_info
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05326375292" }
        - $project: { _id: 0, opportunity_stage: 1 }


# 17 — PRODUCT LOOKUP
- user: "Kartal Market hangi paketleri almış?"
  tool_call:
    name: mongo_aggregate
    intent: get_product_lookup
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { account_name: "Kartal Market" }
        - $project: { _id: 0, customer_num: 1, product_lookup: 1 }

# 18 — LOST REASON
- user: "05067203599 niye kaybedildi?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_info
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05067203599" }
        - $project: { _id: 0, customer_num: 1, lost_reason: 1, lost_reason_detail: 1 }

# 19 — LEAD SOURCE + CLOSE DATE
- user: "05326375292 hangi kanaldan geldi, ne zaman kapandı?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_info
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05326375292" }
        - $project: { _id: 0, customer_num: 1, lead_source: 1, close_date: 1 }

# 20 — CONTACT INFO (e-posta + ad)
- user: "05067203599 müşterisinin e-postası ve adı?"
  tool_call:
    name: mongo_aggregate
    intent: get_contact_info
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05067203599" }
        - $project: { _id: 0, customer_num: 1, contact_name: 1, contact_email: 1 }

# 21 — MULTI-INTENT: transcript + fırsat aşaması + ürün
- user: "Kartal Market’in tüm transcriptlerini ver, fırsat aşamasını ve paketini de ekle"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_by_customer_num
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match: { account_name: "Kartal Market" }
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            transcript: "$calls.cleaned_transcript"
  - tool_call:
      name: mongo_aggregate
      intent: get_opportunity_info
      arguments:
        collection: audio_jobs
        pipeline:
          - $match: { account_name: "Kartal Market" }
          - $project: { _id: 0, opportunity_stage: 1, product_lookup: 1 }


# 22 — LAST CALL + OPPORTUNITY INFO  (🆕 yeni örnek)
- user: "En son konuştuğumuz müşterinin fırsat aşaması, lead source ve e-postası?"
  tool_call:
    name: mongo_aggregate
    intent: get_last_call
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $sort:   { "calls.call_date": -1 }
        - $limit:  1
        - $project:
            _id: 0
            customer_num: "$customer_num"
            call_id:      "$calls.call_id"
            call_date:    "$calls.call_date"
  - tool_call:
      name: mongo_aggregate
      intent: get_opportunity_info
      arguments:
        collection: audio_jobs
        pipeline:
          - $match: { customer_num: "{prev.customer_num}" }  # gateway doldurur
          - $project:
              _id: 0
              customer_num: 1
              opportunity_stage: 1
              lead_source: 1
              contact_email: 1
              contact_name: 1
              close_date: 1
              
# 23 — CALL METRICS (toplam çağrı adedi)
- user: "05011345074 müşterisiyle toplam kaç çağrı yapılmış?"
  tool_call:
    name: mongo_aggregate
    intent: get_call_metrics
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:  { customer_num: "05011345074" }
        - $group:  { _id: null, total_calls: { $sum: 1 } }
        - $project:{ _id: 0, total_calls: 1 }

# 24 — EN ÇOK LEAD LOST NEDENİ (belirli bir günde)
- user: "12 haziran 2025 de en çok hangi lead lost almış?"
  tool_call:
    name: mongo_aggregate  
    intent: get_lost_reason_count  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $match: { "calls.call_date": { $gte: "2025-06-12", $lte: "2025-06-12" } }
        - $unwind: "$calls"
        - $match:  
            $or:  
              - { "lost_reason": { $exists: true } }  
              - { "lost_reason_detail": { $exists: true } }
        - $group:  
            _id:  
              reason: { $ifNull: [ "$lost_reason", "$lost_reason_detail" ] }  
            count: { $sum: 1 }
        - $sort: { count: -1 }
        - $limit: 1
        - $project:  
            _id: 0  
            lost_reason: "$_id.reason"  
            count: 1

# 25 — GÖRÜŞÜLEN TEMSİLCİ SAYISI (kaç farklı kişiyle konuşmuş)
- user: "Bu müşteri kaç farklı temsilciyle görüşmüş?"
  tool_call:
    name: mongo_aggregate  
    intent: get_call_metrics  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $unwind: "$calls"
        - $match: { customer_num: "05000000000" }
        - $group:
            _id: "$customer_num"
            unique_agents: { $addToSet: "$calls.agent_email" }
        - $project:
            _id: 0
            customer_num: "$_id"
            unique_agents_count: { $size: "$unique_agents" }

# 26 — EN UZUN GÖRÜŞMEYİ YAPAN MÜŞTERİ (belirli bir günde)
- user: "12 Haziran 2025’de en uzun görüşmeyi kim yapmış?"
  tool_call:
    name: mongo_aggregate  
    intent: get_call_metrics  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $unwind: "$calls"
        - $match: { "calls.call_date": { $gte: "2025-06-12", $lte: "2025-06-12" } }
        - $sort: { "calls.duration": -1 }
        - $limit: 1
        - $project:
            _id: 0
            customer_num: 1
            agent_email: "$calls.agent_email"
            duration: "$calls.duration"

# 27 — EN ÇOK ÇAĞRI YAPAN MÜŞTERİ (belirli tarihte)
- user: "15 Haziran 2025’de en çok çağrı yapan müşteri kim?"
  tool_call:
    name: mongo_aggregate  
    intent: get_call_metrics  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $unwind: "$calls"
        - $match: { "calls.call_date": { $gte: "2025-06-15", $lte: "2025-06-15" } }
        - $group:
            _id: "$customer_num"
            total_calls: { $sum: 1 }
        - $sort: { total_calls: -1 }
        - $limit: 1
        - $project:
            _id: 0
            customer_num: "$_id"
            total_calls: 1

# 28 — ORTALAMA GÖRÜŞME SÜRESİ EN YÜKSEK MÜŞTERİ (belirli tarihte)
- user: "12 Haziran 2025’de ortalama görüşme süresi en yüksek müşteri kim?"
  tool_call:
    name: mongo_aggregate  
    intent: get_call_metrics  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $unwind: "$calls"
        - $match: { "calls.call_date": { $gte: "2025-06-12", $lte: "2025-06-12" } }
        - $group:
            _id: "$customer_num"
            avg_duration: { $avg: "$calls.duration" }
        - $sort: { avg_duration: -1 }
        - $limit: 1
        - $project:
            _id: 0
            customer_num: "$_id"
            avg_duration: 1

# 29 — FARKLI GÜNLERDE GÖRÜŞME YAPMIŞ MÜŞTERİ SAYISI
- user: "Kaç farklı gün görüşme yapılmış?"
  tool_call:
    name: mongo_aggregate  
    intent: get_call_metrics  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $unwind: "$calls"
        - $group:
            _id: "$calls.call_date"
        - $count: "unique_days"

# 30 — EN ÇOK WON YAPAN OWNER (belirli günde)
- user: "12 haziran 2025 de en won alan opportunity owner email kime ait ve ne kadar?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_owner_stats
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "2025-06-12"
              $lte: "2025-06-12"
            opportunity_stage: "Closed Won"
        - $group:
            _id: "$opportunity_owner_email"
            total_amount: { $sum: "$amount" }
            won_count: { $sum: 1 }
        - $sort:
            total_amount: -1
        - $limit: 1
        - $project:
            _id: 0
            owner_email: "$_id"
            total_amount: 1
            won_count: 1

  # 31 — EN YÜKSEK WON ORANINA SAHIP OWNER(belirli aralıkta)
- user: "1 Ocak 2024 ile 15 Haziran 2025 arasında konuşma sayısı ve kazanma oranı olarak en yüksek performanslı opportunity e-posta sahibi kimdir?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_owner_stats
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "2024-01-01"
              $lte: "2025-06-15"
        - $group:
            _id: "$opportunity_owner_email"
            total_calls: { $sum: 1 }
            won_count:
              $sum:
                $cond: [{ $eq: ["$opportunity_stage", "Closed Won"] }, 1, 0]
        - $addFields:
            won_rate:
              $cond:
                - { $eq: ["$total_calls", 0] }
                - 0
                - { $divide: ["$won_count", "$total_calls"] }
        - $sort:
            won_rate: -1
        - $limit: 1
        - $project:
            _id: 0
            owner_email: "$_id"
            total_calls: 1
            won_count: 1
            won_rate: 1

  # 32 — BUGÜN EN ÇOK KAZANAN OPPORTUNITY OWNER
- user: "bugün en çok kazanan opportunity owner kim ve kaç tane kazanmış?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_owner_stats
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "{today}"
              $lte: "{today}"
            opportunity_stage: "Closed Won"
        - $group:
            _id: "$opportunity_owner_email"
            won_count: { $sum: 1 }
        - $sort:
            won_count: -1
        - $limit: 1
        - $project:
            _id: 0
            owner_email: "$_id"
            won_count: 1

# 33 — CONVERSION PROBABILITY (alış yapma olasılığı)
- user: "05011345074 müşterisinin dönüşüm olasılığı nedir?"
  tool_call:
    name: mongo_aggregate
    intent: get_conversion_probability
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            conversion_probability: "$mini_rag.conversion_probability"

# 34 — RISK SCORE (satış kaybı riski)
- user: "Bu müşterinin satış riski ne kadar yüksek?"
  tool_call:
    name: mongo_aggregate
    intent: get_risk_score
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            risk_score: "$mini_rag.risk_score"

# 35 — NEXT STEPS (müşteri ve temsilci için önerilen adımlar)
- user: "Bu müşteri için neler öneriliyor, temsilci ne yapmalı?"
  tool_call:
    name: mongo_aggregate
    intent: get_next_steps
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            next_steps: "$mini_rag.next_steps"

# 36 — AUDIO ANALYSIS COMMENTARY (ses analizi yorumları)
- user: "Ses analizine göre temsilci nasıl bir performans sergilemiş?"
  tool_call:
    name: mongo_aggregate
    intent: get_audio_analysis_commentary
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            commentary: "$mini_rag.audio_analysis.audio_analysis_commentary"

# 37 — SENTIMENT + EMOTION SHIFT SCORE
- user: "Bu görüşmelerde müşteri pozitif mi? Duygu dalgalanması var mı?"
  tool_call:
    name: mongo_aggregate
    intent: get_sentiment_analysis
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            sentiment: "$mini_rag.audio_analysis.sentiment"
            emotion_shift_score: "$mini_rag.audio_analysis.emotion_shift_score"


