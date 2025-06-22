🧱 1. call_records Verisinin Kaynağı ve Güncellenmesi
✅ sync_call_records.py (ana script)

    Amaç: Alotech API’den call_details_list verilerini çekip call_records koleksiyonuna kaydeder.

    Senaryo: start_date → end_date arası çağrıları dilimleyerek (15dk alt sınır), MongoDB’ye call_key ile upsert eder.

    Not: Token yenileme, rate-limit, hata yönetimi var.

🧲 2. Salesforce & Leads Verisi Aktarımı
✅ xls_to_mongo_sf_leads_raw.py

    Amaç: salesforce_export.xls dosyasındaki lead verilerini sf_leads_raw koleksiyonuna yükler.

    İşlem: Alanları normalize eder (tarih, telefon), MongoDB’ye upsert yapar.

✅ xls_to_mongo_close_won.py

    Amaç: close_won.xlsx dosyasını sf_close_won_raw koleksiyonuna yükler.

    İşlem: Telefon ve e-posta normalize edilir, tarih alanları ISO formatına çevrilir.

📞 3. Salesforce Kapanan Fırsatlar ile Eşleşen Çağrılar
✅ won_calls_extract.py

    Amaç: call_records içindeki çağrılardan, sf_close_won_raw verisine uyanları won_calls koleksiyonuna atar.

    Eşleşme: Telefon & e-posta üzerinden yapılır, duration ≥ 40s filtresiyle.

🧠 4. audio_jobs Sistemine Geçiş (İşlenebilir Hale Getirme)
✅ enqueue_audio_jobs.py

    Amaç: won_calls içindeki çağrıları customer_num bazlı gruplayarak audio_jobs koleksiyonuna taşır.

    Her müşteri için: calls[] dizisi oluşturulur. Her çağrıda: call_id, call_key, agent_email, call_date, status: queued.

    Job durumu: queued, partial, done, error olarak job_status alanında tutulur.

🔽 5. Ses Dosyası İndirme
✅ download_recordings.py

    Amaç: audio_jobs.calls[].status == "queued" olanları Alotech’ten indirir.

    Kayıt: recordings/<customer>/<tarih_callid>.wav şeklinde diske yazar.

    Durum güncelleme: downloaded, error, file_path, downloaded_at.

🧾 6. Transkripsiyon (WhisperX + Pyannote)
✅ transcribe_worker.py

    Amaç: downloaded durumundaki çağrıları işleyip:

        FFmpeg ile temizler,

        WhisperX ile transkripte çevirir,

        Pyannote ile speaker diarization yapar,

        Müşteri ve temsilciyi ayırır,

        output/<customer>/<call_id>.txt olarak kaydeder.

🧹 7. Transkript Temizleme (OpenAI)
✅ clean_transcripts.py

    Amaç: cleaned_transcript alanı olmayan çağrılar için GPT ile:

        Tekrar, gürültü, çakışma düzeltmesi yapar,

        Temsilci: / Müşteri: satırlarıyla düzenler,

        MongoDB’ye calls[].cleaned_transcript alanına kaydeder,

        Aynı anda cleaned_output/<customer>/<call_id>.txt olarak diske yazar.

🧪 8. Random Veri Örneği Çekme
✅ full_random_dump.py

    Amaç: call_records koleksiyonundan n adet rastgele belgeyi .jsonl(.gz) formatında diske yazar.

    Kullanım: Test verisi çıkarmak için ideal.

