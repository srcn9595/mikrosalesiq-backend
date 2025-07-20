# prompt_examples.md  ·  2025-06 rev-01
# ────────────────────────────────────────────────────────────────
# NOT: Her örnek → tek bir “ideal” tool_call gösterir.
#     {name, arguments, intent} alanları bire bir manifest ile eşleşir.
# ────────────────────────────────────────────────────────────────


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

# 21 — MULTI-FIELD: transcript + fırsat aşaması + ürün
- user: "05324343294 müşterisinin tüm transkriptleriyle birlikte fırsat aşamasını ve paketini getir"
  tool_call:
    name: mongo_aggregate
    intent: get_transcripts_and_opportunity
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match: { customer_num: "05324343294" }
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            transcript: "$calls.cleaned_transcript"
            opportunity_stage: 1
            product_lookup: 1


# 22 — LAST CALL + OPPORTUNITY INFO
- user: "En son konuştuğumuz müşterinin fırsat aşaması, lead source ve e-postası?"
  tool_call:
    name: mongo_aggregate
    intent: get_last_call_and_opportunity_info
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $sort:   { "calls.call_date": -1 }
        - $limit:  1
        - $project:
            _id: 0
            customer_num: "$customer_num"
            call_id: "$calls.call_id"
            call_date: "$calls.call_date"
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
- user: "12 Haziran 2025'te en çok hangi nedenle lead kaybedilmiş?"
  tool_call:
    name: mongo_aggregate  
    intent: get_lost_reason_count  
    arguments:  
      collection: audio_jobs  
      pipeline:
        - $match:
            close_date:
              $gte: "2025-06-12T00:00:00"
              $lt:  "2025-06-13T00:00:00"
        - $match:
            $or:
              - { lost_reason: { $exists: true, $ne: null } }
              - { lost_reason_detail: { $exists: true, $ne: null } }
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
        - $match:
            calls.call_date:
              $gte: "2025-06-12T00:00:00"
              $lt:  "2025-06-13T00:00:00"
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
        - $match:
            calls.call_date:
              $gte: "2025-06-15T00:00:00"
              $lt:  "2025-06-16T00:00:00"
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
        - $match:
            calls.call_date:
              $gte: "2025-06-12T00:00:00"
              $lt:  "2025-06-13T00:00:00"
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
        - $match:
            calls.call_date:
              $gte: "2025-06-12"
              $lte: "2025-06-12"
            opportunity_stage: "Closed Won"
        - $group:
            _id:
              owner_email: "$opportunity_owner_email"
              customer_num: "$customer_num"
            amount: { $first: "$amount" }  # Aynı müşteri için ilk değer
        - $group:
            _id: "$_id.owner_email"
            total_amount: { $sum: "$amount" }
            won_count: { $sum: 1 }
        - $sort: { total_amount: -1 }
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
        - $match:
            calls.call_date:
              $gte: "2024-01-01"
              $lte: "2025-06-15"
        - $group:
            _id:
              owner_email: "$opportunity_owner_email"
              customer_num: "$customer_num"
              is_won: { $eq: [ "$opportunity_stage", "Closed Won" ] }
        - $group:
            _id: "$_id.owner_email"
            total_customers: { $sum: 1 }
            won_customers:
              $sum: { $cond: ["$_id.is_won", 1, 0] }
        - $addFields:
            won_rate:
              $cond:
                - { $eq: ["$total_customers", 0] }
                - 0
                - { $divide: ["$won_customers", "$total_customers"] }
        - $sort: { won_rate: -1 }
        - $limit: 1
        - $project:
            _id: 0
            owner_email: "$_id"
            total_customers: 1
            won_customers: 1
            won_rate: 1


  # 32 — BUGÜN EN ÇOK KAZANAN OPPORTUNITY OWNER
- user: "bugün en çok kazanan opportunity owner kim ve kaç tane kazanmış?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_owner_stats
    arguments:
      collection: audio_jobs
      pipeline:
        - $match:
            calls.call_date: { $gte: "{today}", $lte: "{today}" }
            opportunity_stage: "Closed Won"
        - $group:
            _id:
              owner_email: "$opportunity_owner_email"
              customer_num: "$customer_num"
        - $group:
            _id: "$_id.owner_email"
            won_count: { $sum: 1 }
        - $sort: { won_count: -1 }
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

- user: "10 Haziran 2024’ten sonra lead’i kaybedilmiş ama dönüşüm olasılığı en yüksek 5 müşteriyi dönüşüm oranı, çağrı tarihi ve temsilcisiyle birlikte getir."
  tool_call:
    name: mongo_aggregate
    intent: get_conversion_probability
    arguments:
      collection: audio_jobs
      pipeline:
        - $match:
            opportunity_stage: "Closed Lost"
            mini_rag.conversion_probability: { $exists: true, $ne: null }
        - $unwind: "$calls"
        - $match:
            calls.call_date: { $gte: "2024-06-10" }
        - $sort:
            calls.call_date: -1
        - $group:
            _id: "$customer_num"
            conversion_probability: { $first: "$mini_rag.conversion_probability" }
            agent_email: { $first: "$calls.agent_email" }
            call_date: { $first: "$calls.call_date" }
            account_name: { $first: "$account_name" }
        - $sort:
            conversion_probability: -1
        - $limit: 5
        - $project:
            _id: 0
            customer_num: "$_id"
            account_name: 1
            conversion_probability: 1
            agent_email: 1
            call_date: 1


# 39 — CUSTOMER SCORECARD
- user: "05011345074 müşterisinin detaylı skor kartını ver"
  tool_call:
    name: mongo_aggregate
    intent: get_customer_scorecard
    arguments:
      collection: audio_jobs
      pipeline:
        - $match: { customer_num: "05011345074" }
        - $project:
            _id: 0
            customer_num: 1
            conversion_probability: "$mini_rag.conversion_probability"
            risk_score: "$mini_rag.risk_score"
            sentiment: "$mini_rag.audio_analysis.sentiment"
            emotion_shift_score: "$mini_rag.audio_analysis.emotion_shift_score"
            summary: "$mini_rag.summary"
            next_steps: "$mini_rag.next_steps"
            commentary: "$mini_rag.audio_analysis.audio_analysis_commentary"

# 40 — OPPORTUNITY STAGE BREAKDOWN
- user: "Tüm fırsatların hangi aşamada kaç adet olduğunu özetler misin?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_stage_distribution
    arguments:
      collection: audio_jobs
      pipeline:
        - $group:
            _id: "$opportunity_stage"
            count: { $sum: 1 }
        - $project:
            _id: 0
            stage: "$_id"
            count: 1

# 41 — TOP CUSTOMERS BY COMBINED SCORE
- user: "En hızlı dönüşüm sağlayabileceğimiz 5 müşteriyi sırala"
  tool_call:
    name: mongo_aggregate
    intent: get_combined_score_customers
    arguments:
      collection: audio_jobs
      pipeline:
        - $project:
            customer_num: 1
            conversion_probability: "$mini_rag.conversion_probability"
            risk_score: "$mini_rag.risk_score"
        - $addFields:
            combined_score: {
              $subtract: [ "$conversion_probability", "$risk_score" ]
            }
        - $sort: { combined_score: -1 }
        - $limit: 5
        - $project:
            _id: 0
            customer_num: 1
            conversion_probability: 1
            risk_score: 1
            combined_score: 1

# 42 — HIGH RISK NEGATIVE MÜŞTERİLER
- user: "Kritik seviyede riskli ve negatif konuşan müşterileri bul"
  tool_call:
    name: mongo_aggregate
    intent: get_critical_alerts
    arguments:
      collection: audio_jobs
      pipeline:
        - $match:
            mini_rag.risk_score: { $gte: 0.8 }
            mini_rag.audio_analysis.sentiment: "negative"
        - $project:
            _id: 0
            customer_num: 1
            risk_score: "$mini_rag.risk_score"
            sentiment: "$mini_rag.audio_analysis.sentiment"
            summary: "$mini_rag.summary"

# 43 — EN ÇOK WON MÜŞTERİ KAZANAN 5 TEMSİLCİ
- user: "2025 yılı içinde en çok müşteriyi kazanan ilk 5 temsilci kim?"
  tool_call:
    name: mongo_aggregate
    intent: get_opportunity_owner_stats
    arguments:
      collection: audio_jobs
      pipeline:
        - $match:
            calls.call_date:
              $gte: "2025-01-01"
              $lte: "2025-12-31"
            opportunity_stage: "Closed Won"
        - $group:
            _id: "$opportunity_owner_email"
            won_count: { $sum: 1 }
        - $sort: { won_count: -1 }
        - $limit: 5
        - $project:
            _id: 0
            owner_email: "$_id"
            won_count: 1

# 44 — EN ÇOK POZİTİF GERİ BİLDİRİM ALAN 3 TEMSİLCİ (sentiment & konu)
- user: "Son 1 ayda en çok pozitif görüşme yapmış 3 temsilci kim?"
  tool_call:
    name: mongo_aggregate
    intent: get_agent_sentiment_summary
    arguments:
      collection: audio_jobs
      pipeline:
        - $unwind: "$calls"
        - $match:
            calls.call_date:
              $gte: "{today-1m}"
            mini_rag.audio_analysis.sentiment: "positive"
        - $group:
            _id: "$calls.agent_email"
            positive_call_count: { $sum: 1 }
            topics: { $addToSet: "$mini_rag.topic_summary" }
        - $sort: { positive_call_count: -1 }
        - $limit: 3
        - $project:
            _id: 0
            agent_email: "$_id"
            positive_call_count: 1
            topics: 1

# 45 — MÜŞTERİ TİPİNE GÖRE ORTAK DÖNÜŞÜM PROBLEMİ ANALİZİ
- user: "Benzer müşterilerde dönüşüm problemlerinin ortak nedenleri ne olabilir?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "müşteriler neden dönüşmüyor?"
      top_k: 10
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }

# 46 — SATIŞA DÖNÜŞMEYENLERDE ORTAK ENGELLER
- user: "Satışa dönüşemeyen müşterilerde tekrar eden problemler neler?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "neden satışa dönüşemiyorlar?"
      top_k: 10
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }

# 47 — KAYBEDİLEN MÜŞTERİ PROFİL ANALİZİ
- user: "Kaybettiğimiz müşterilerin profilleri nasıldı?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "müşteri kaybı neden yaşanıyor?"
      top_k: 15
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $in: ["Closed Lost", "Lead Lost"] }

# 48 — TEMSİLCİ PERFORMANSI ZAYIF NOKTALAR
- user: "Satışı kaçırdığımız müşterilerde temsilciler hangi konularda yetersiz kalmış?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "temsilci eksikleri"
      top_k: 15
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }

# 49 — SATIN ALAN MÜŞTERİLERDE ORTAK PROFİL
- user: "Satın alan müşterilerde ortak profil nedir?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "dönüşmüş müşteriler nasıl?"
      top_k: 7
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: "Closed Won"

# 50 — EN VERİMLİ MÜŞTERİ SEGMENTLERİ
- user: "En çok satış yaptığımız segmentler neler?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "en verimli segment"
      top_k: 10
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: "Closed Won"

# 51 — DÖNÜŞÜM POTANSİYELİ YÜKSEK MÜŞTERİ PROFİLİ
- user: "Dönüşme potansiyeli yüksek müşteriler hangi özellikleri taşıyor?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "yüksek dönüşüm olasılığı"
      top_k: 20
      threshold: 0.35
      pipeline:
        - $match:
            mini_rag.conversion_probability: { $gte: 0.60 }

# 52 — MÜŞTERİ KAYIPLARININ ORTAK SEBEPLERİ
- user: "Müşteriler neden kaybediliyor olabilir?"
  tool_call:
    name: vector_customer
    intent: get_customer_patterns
    arguments:
      query: "müşteriler neden kaybediliyor olabilir?"
      top_k: 15
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $in: ["Closed Lost", "Lead Lost"] }

# 53 — SON 1 AYDAKİ MÜŞTERİ KAYIPLARI
- user: "Son 1 ayda neden bu kadar müşteri kaybettik?"
  tool_call:
    name: insight_engine
    intent: get_lost_reason_analysis
    arguments:
      query: "kapanmayan fırsatlarda tekrar eden temsilci ya da süreç hataları"
      top_k: 20
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }
            close_date: { $gte: "2025-06-18T00:00:00" }
        - $project:
            _id: 0
            customer_num: 1
            lost_reason: 1
            lost_reason_detail: 1
            opportunity_owner: 1
            close_date: 1
            mini_rag.summary: 1
            mini_rag.common_issues: 1
            mini_rag.recommendations: 1
            mini_rag.risk_score: 1
            mini_rag.next_steps: 1

# 54 — DÜŞÜK DÖNÜŞÜMLÜ MÜŞTERİ SEGMENTLERİ
- user: "İkna etmekte zorlandığımız müşteri segmentleri neler?"
  tool_call:
    name: insight_engine
    intent: get_low_conversion_segments
    arguments:
      query: "düşük dönüşüm oranına sahip müşteri profilleri ve ortak itirazlar"
      top_k: 15
      threshold: 0.40
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }
        - $project:
            _id: 0
            customer_num: 1
            mini_rag.customer_profile.sector: 1
            mini_rag.customer_profile.personality_type: 1
            mini_rag.customer_profile.needs: 1
            mini_rag.conversion_probability: 1
            mini_rag.common_issues: 1
            mini_rag.recommendations: 1

# 55 — SES TONU & SATIŞ BAŞARISI
- user: "Ses analizlerine göre başarılı temsilciler nasıl bir tonlama kullanıyor?"
  tool_call:
    name: insight_engine
    intent: get_successful_audio_patterns
    arguments:
      query: "ses tonu ve ifade şekli ile satış başarısı ilişkisi"
      top_k: 10
      threshold: 0.25
      pipeline:
        - $match:
            opportunity_stage: "Closed Won"
        - $unwind: "$calls"
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            agent_email: "$calls.agent_email"
            audio_features: "$calls.audio_features"
            audio_analysis_commentary: "$calls.audio_analysis_commentary"

# 56 — MÜŞTERİYE YAKLAŞIM STRATEJİSİ
- user: "05067203599 numaralı müşteriyle görüşeceğim, geçmişe göre nasıl yaklaşmalıyım?"
  tool_call:
    name: insight_engine
    intent: get_customer_specific_tactics
    arguments:
      query: "müşteri ihtiyaçları, hassasiyetleri ve ikna için taktikler"
      pipeline:
        - $match:
            customer_num: "05067203599"
        - $project:
            _id: 0
            customer_num: 1
            mini_rag.summary: 1
            mini_rag.customer_profile: 1
            mini_rag.recommendations: 1
            mini_rag.next_steps: 1
            mini_rag.risk_score: 1
            mini_rag.conversion_probability: 1

# 57 — BAŞARILI SATIŞLARDA ORTAK STRATEJİLER
- user: "Haziran ayında kazanılan müşterilerde en etkili satış taktiği ne olmuş?"
  tool_call:
    name: insight_engine
    intent: get_successful_sales_strategies
    arguments:
      query: "başarılı satışlarda tekrar eden ikna stratejileri"
      top_k: 15
      threshold: 0.35
      pipeline:
        - $match:
            opportunity_stage: "Closed Won"
            close_date: { $gte: "2025-06-01T00:00:00", $lt: "2025-07-01T00:00:00" }
        - $project:
            _id: 0
            customer_num: 1
            mini_rag.summary: 1
            mini_rag.recommendations: 1
            mini_rag.sales_scores: 1
            mini_rag.segments: 1

# 58 — YÜKSEK RİSKLİ MÜŞTERİ PROFİLLERİ
- user: "Son zamanlarda en çok risk taşıyan müşteri profili hangisi?"
  tool_call:
    name: insight_engine
    intent: get_high_risk_profiles
    arguments:
      query: "yüksek risk skoru taşıyan müşteri tipolojisi"
      top_k: 10
      threshold: 0.40
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }
        - $project:
            _id: 0
            customer_num: 1
            mini_rag.customer_profile: 1
            mini_rag.risk_score: 1
            mini_rag.summary: 1
            mini_rag.common_issues: 1

# 59 — KAYBEDİLEN FIRSATLARDA GERİ KAZANIM
- user: "Geçtiğimiz ay kapatamadığımız fırsatları kazanmak için neler yapmalıyız?"
  tool_call:
    name: insight_engine
    intent: get_win_back_tactics
    arguments:
      query: "kapanmayan fırsatlarda önerilen taktikler ve geri kazanım önerileri"
      top_k: 12
      threshold: 0.30
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }
            close_date: { $gte: "2025-06-18T00:00:00" }
        - $project:
            _id: 0
            customer_num: 1
            lost_reason: 1
            mini_rag.summary: 1
            mini_rag.recommendations: 1
            mini_rag.next_steps: 1
            mini_rag.risk_score: 1

# 60 — TEMSİLCİ İLETİŞİM TARZI ANALİZİ
- user: "İletişim tarzımız müşterilerde nasıl bir etki bırakıyor olabilir?"
  tool_call:
    name: insight_engine
    intent: get_communication_style_impact
    arguments:
      query: "temsilcilerin iletişim tarzlarının olumlu ve olumsuz etkileri"
      top_k: 10
      threshold: 0.30
      pipeline:
        - $match:
            opportunity_stage: { $ne: "Closed Won" }
        - $unwind: "$calls"
        - $project:
            _id: 0
            call_id: "$calls.call_id"
            cleaned_transcript: "$calls.cleaned_transcript"
            audio_features: "$calls.audio_features"
            audio_analysis_commentary: "$calls.audio_analysis_commentary"
            mini_rag.sales_scores: 1

# 61 — TEK MÜŞTERİLİ HATA ANALİZİ
- user: "0509991122 müşteri numaralı kayıpta neyi yanlış yapmış olabiliriz?"
  tool_call:
    name: insight_engine
    intent: get_individual_failure_analysis
    arguments:
      query: "müşterinin ikna olmama nedenleri, eksik iletişim ya da öneri eksiklikleri"
      pipeline:
        - $match:
            customer_num: "0509991122"
        - $project:
            _id: 0
            customer_num: 1
            lost_reason: 1
            mini_rag.summary: 1
            mini_rag.recommendations: 1
            mini_rag.next_steps: 1
            mini_rag.risk_score: 1
            mini_rag.common_issues: 1