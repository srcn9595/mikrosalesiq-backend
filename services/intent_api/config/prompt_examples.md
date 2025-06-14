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
    intent: get_call_dates
    arguments:
      collection: call_records
      pipeline:
        - $match:
            $or:
              - caller_id: "05445118257"
              - called_num: "05445118257"
        - $sort: { call_date: -1 }
        - $limit: 1
        - $project: { _id: 0, call_id: "$call_id", call_date: "$call_date", agent_email: "$agent_email" }

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

# 14 — AGENT CONTACT LIST (son 2 ay, inbound+outbound ayrımı)
- user: "arda.eksioglu@parasut.com son 2 ayda kimlerle görüşmüş?"
  tool_call:
    name: mongo_aggregate
    intent: get_call_dates
    arguments:
      collection: call_records
      pipeline:
        - $match:
            agent_email: "arda.eksioglu@parasut.com"
            call_date: { $gte: "{today-2m}" }
        - $project:
            _id: 0
            call_id:    "$call_id"
            call_date:  "$call_date"
            customer_num:
              $cond: [ "$is_inbound", "$caller_id", "$called_num" ]


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
            agent_email: "$calls.agent_email"
            transcript: "$calls.cleaned_transcript"


