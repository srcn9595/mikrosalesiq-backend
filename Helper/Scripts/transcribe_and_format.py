import os
import subprocess
import torch,inspect
import torch.serialization
from omegaconf.listconfig import ListConfig
from omegaconf.base import ContainerMetadata

import whisperx
from dotenv import load_dotenv
from pymongo import MongoClient
from pathlib import Path
from pyannote.audio import Pipeline
from pyannote.core import Segment

if hasattr(torch.serialization, "add_safe_globals"):
    torch.serialization.add_safe_globals([ListConfig, ContainerMetadata])

# ENV değişkenlerini yükle
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "alotech"
COLL_NAME = "audio_jobs"

# Cihaz kontrolü
device = "cuda" if torch.cuda.is_available() else "cpu"



# WhisperX modelini yükle
model = whisperx.load_model("large-v3", device=device)

# pyannote diarization pipeline (v3.1)
diarize_model = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=HF_TOKEN
)

# FFmpeg ile ses temizleme
def clean_audio(input_path: str, output_path: str):
    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-af", "afftdn, dynaudnorm, silenceremove=start_periods=1:start_duration=0.3:start_threshold=-40dB, loudnorm",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path
    ], check=True)

# Whisper segmentlerini speaker diarization ile hizala

def align_segments_with_speakers(whisper_segments, diarization):
    """
    whisper_segments:  result["segments"] çıktısı (dict listesi)
    diarization:       pyannote.core.Annotation

    Her Whisper segmentine en çok çakışan konuşmacı etiketini ekler.
    """
    # diarization'ı tek seferde listeye alalım → inner loop’ta GPU boş kalır
    tracks = list(diarization.itertracks(yield_label=True))

    aligned = []
    for seg in whisper_segments:
        w_start, w_end = seg["start"], seg["end"]

        # çakışma arayan basit aralık mantığı
        for turn, _, speaker in tracks:
            if turn.start <= w_end and turn.end >= w_start:
                seg["speaker"] = speaker
                break      # ilk eşleşme yeterli

        # eşleşme bulunamazsa etiket koyma (opsiyonel)
        seg.setdefault("speaker", "Unknown")
        aligned.append(seg)

    return aligned

# Çıktıyı metin haline getir
def format_output(segments, customer, agent):
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "Konuşmacı")
        label = agent if speaker == "SPEAKER_00" else customer
        lines.append(f"{label}: {seg['text'].strip()}")
    return "\n".join(lines)

# Her bir çağrıyı işle
def process_call(doc, call):
    audio_path = call.get("file_path")
    if not audio_path or not os.path.exists(audio_path):
        print(f"⚠️ Dosya eksik: {audio_path}")
        return

    customer = doc["customer_num"]
    agent = call.get("agent_email", "Temsilci")
    call_id = call["call_id"]
    cleaned_path = f"temp/cleaned_{call_id}.wav"
    os.makedirs("temp", exist_ok=True)

    print(f"🎧 Temizleniyor: {audio_path}")
    clean_audio(audio_path, cleaned_path)

    print(f"🧠 Transkripsiyon başlıyor: {call_id}")
    result = model.transcribe(cleaned_path, batch_size=4)

    print(f"👥 Diarizasyon başlıyor: {call_id}")
    diarization = diarize_model(cleaned_path)

    print(f"🧩 Segmentler hizalanıyor...")
    aligned_segments = align_segments_with_speakers(result["segments"], diarization)

    out_dir = Path("output") / customer
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{call_id}.txt"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(format_output(aligned_segments, customer, agent))

    print(f"✅ Transkript tamamlandı: {out_path}")
    os.remove(cleaned_path)

# MongoDB üzerinden tüm çağrıları sırayla al ve işle
def main():
    client = MongoClient(MONGO_URI)
    coll = client[DB_NAME][COLL_NAME]

    cursor = coll.find({
        "calls.status": "downloaded",
        "calls.file_path": {"$exists": True}
    })

    for doc in cursor:
        for call in doc.get("calls", []):
            if call.get("status") == "downloaded" and call.get("file_path"):
                try:
                    process_call(doc, call)
                except Exception as e:
                    print(f"❌ Hata ({call.get('call_id')}): {e}")

if __name__ == "__main__":
    main()
