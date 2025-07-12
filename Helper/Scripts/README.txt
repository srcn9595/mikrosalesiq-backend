🧱 1. call_records Verisinin Kaynağı ve Güncellenmesi
✅ fetch_call_list.py (ana script)

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

    9. Veri Temizleme

    Amaç: audio_jobs dosyasında mini rag işleminden sonra belli error vs log lar silinmesi amacıyla yapılmıştır. Zaten mini rag çıkartıldıysa error çözülmüştür.
    Kullanım: Run et çalıştır okey. Daha sonra hangfire gibi job a atılacak her gece çalışması için. 

    10. Veri Resetleme

    Amaç: audio_jobs dosyasında gerek test için gerekse bir problem olmasında sıfırlamak için yazılmıştır. Fonksiyon yetkiye bağlı olarak belki eklenebilir.
    Kullanım: Run et çalıştır. Muhtemelen frondend e bir buton bir alan konulur yeniden hesapla gibi resetle vs gibi bişey olur o customer num ile tüm bilgiler sıfırlanır. 

9. Qdrant Kurulumu (Canlı Sunucuya Alma)
=========================================
cd ~/qdrant
wget https://github.com/qdrant/qdrant/releases/download/v1.14.0/qdrant_1.14.0-1_amd64.deb
sudo dpkg -i qdrant_1.14.0-1_amd64.deb

Adım 3: Çalışma klasörünü oluştur
---------------------------------
sudo mkdir -p /var/lib/qdrant
sudo chown $USER:$USER /var/lib/qdrant

Adım 4: systemd servis dosyasını oluştur
----------------------------------------
sudo nano /etc/systemd/system/qdrant.service

# İçerik:
[Unit]
Description=Qdrant Vector Database
After=network.target

[Service]
ExecStart=/usr/bin/qdrant
WorkingDirectory=/var/lib/qdrant
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target

Adım 5: Servisi aktif hale getir
-------------------------------
sudo systemctl daemon-reload
sudo systemctl enable qdrant
sudo systemctl start qdrant
sudo systemctl status qdrant

# Eğer çıktı "active (running)" ise başarıyla çalışıyor demektir.

Adım 6: Port ve erişim kontrolü
-------------------------------
- HTTP API (varsayılan): http://localhost:6333
- Dış erişim gerekiyorsa:
    - 6333 portu açılmalı (firewall/security group)
    - Gerekirse nginx reverse proxy ve TLS eklenebilir.

Adım 7: Test et
---------------
curl http://localhost:6333

# Beklenen çıktı:
{"title":"qdrant - vector search engine","version":"1.14.0", ...}

Notlar:
-------
- Hata varsa logları kontrol et:
  journalctl -u qdrant.service -f
- Elle çalışıyorsa ve systemctl hata veriyorsa:
  /var/lib/qdrant izinlerini ve qdrant.service içindeki WorkingDirectory satırını kontrol et.

  sudo ip addr add 172.17.0.1 dev docker0
  QDRANT_HOST=172.17.0.1
  QDRANT_PORT=6333