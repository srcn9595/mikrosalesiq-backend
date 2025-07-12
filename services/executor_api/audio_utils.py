import librosa
import numpy as np
from collections import defaultdict
import os
import logging,traceback
from transformers import pipeline

log = logging.getLogger("audio_features")
classifier = pipeline("text-classification", model="savasy/bert-base-turkish-sentiment-cased", return_all_scores=True)

def extract_audio_features(audio_path: str, call_id: str, collection) -> dict:
    try:
        y, sr = librosa.load(audio_path, sr=None)
        duration = librosa.get_duration(y=y, sr=sr)
        log.debug("Loaded wav: sr=%d  duration=%.2f", sr, duration)

        segments = get_diarization_segments(call_id, collection)
        if not segments:
            log.error("Diarization segments boş! call_id=%s", call_id)
            return {}


        for seg in segments:
            seg["speaker"] = normalize_speaker(seg.get("speaker"))

        agent_speaking = [(s["start"], s["end"]) for s in segments if s["speaker"] == "agent"]
        customer_speaking = [(s["start"], s["end"]) for s in segments if s["speaker"] == "customer"]

        agent_total = sum(e - s for s, e in agent_speaking)
        customer_total = sum(e - s for s, e in customer_speaking)

        total_talk = agent_total + customer_total
        agent_talk_ratio = agent_total / total_talk if total_talk else 0

        agent_pitch_var = pitch_variance(y, sr, agent_speaking)
        customer_pitch_var = pitch_variance(y, sr, customer_speaking)

        agent_words = sum(len(s['text'].split()) for s in segments if s['speaker'] == 'agent')
        customer_words = sum(len(s['text'].split()) for s in segments if s['speaker'] == 'customer')

        speaking_rate_agent = agent_words / agent_total * 60 if agent_total else 0
        speaking_rate_customer = customer_words / customer_total * 60 if customer_total else 0

        overlap_duration = compute_overlap_duration(segments)
        agent_overlap_rate = overlap_duration / duration if duration else 0

        customer_filler_count = sum(count_fillers(s['text']) for s in segments if s['speaker'] == 'customer')

        agent_silence_ratio = compute_silence_ratio(segments, "agent", duration)
        customer_silence_ratio = compute_silence_ratio(segments, "customer", duration)

        dominant_speaker = get_dominant_speaker(segments)
        emotion_shift_score = compute_emotion_shift(audio_path, segments)

        return {
            "duration_seconds": round(duration),
            "dominant_speaker": dominant_speaker,
            "speaking_rate_customer": round(speaking_rate_customer, 1),
            "speaking_rate_agent": round(speaking_rate_agent, 1),
            "agent_overlap_rate": round(agent_overlap_rate, 2),
            "customer_filler_count": customer_filler_count,
            "agent_pitch_variance": round(float(agent_pitch_var), 1),
            "customer_pitch_variance": round(float(customer_pitch_var), 1),
            "agent_silence_ratio": round(agent_silence_ratio, 2),
            "customer_silence_ratio": round(customer_silence_ratio, 2),
            "agent_talk_ratio": round(agent_talk_ratio, 2),
            "emotion_shift_score": round(emotion_shift_score, 2)
        }

    except Exception as e:
        log.error("[%s] feature extraction crash: %s\n%s",
                  call_id, e, traceback.format_exc(limit=2))
        return {}
# --- Yardımcı fonksiyonlar ---

def normalize_speaker(speaker: str) -> str:
    if speaker == "SPEAKER_00":
        return "agent"
    elif speaker == "SPEAKER_01":
        return "customer"
    return speaker

def get_diarization_segments(call_id: str, collection):
    rec = collection.find_one({"calls.call_id": call_id}, {"calls.$": 1})
    if not rec or not rec.get("calls"):
        return []
    return rec["calls"][0].get("segments", [])

def get_transcript(call_id: str, collection):
    rec = collection.find_one({"calls.call_id": call_id}, {"calls.$": 1})
    if not rec or not rec.get("calls"):
        return []
    return rec["calls"][0].get("transcript", [])

def get_dominant_speaker(segments: list[dict]) -> str:
    durations = defaultdict(float)
    for s in segments:
        speaker = s.get("speaker")
        if speaker:
            durations[speaker] += s["end"] - s["start"]
    return max(durations, key=durations.get) if durations else "unknown"

def pitch_variance(y, sr, segment_list):
    pitches = []
    for start, end in segment_list:
        start_sample = int(start * sr)
        end_sample = int(end * sr)
        y_seg = y[start_sample:end_sample]
        pitch, _ = librosa.piptrack(y=y_seg, sr=sr)
        pitches.extend(pitch[pitch > 0].flatten())
    return float(np.var(pitches)) if pitches else 0


def compute_overlap_duration(segments):
    total_overlap = 0.0
    sorted_segs = sorted(segments, key=lambda s: s["start"])

    for i in range(len(sorted_segs) - 1):
        a = sorted_segs[i]
        b = sorted_segs[i + 1]
        if a["end"] > b["start"]:
            total_overlap += min(a["end"], b["end"]) - b["start"]
    return total_overlap

def count_fillers(text):
    fillers = ["ıı", "ee", "şey", "yani", "hani", "aslında"]
    return sum(text.lower().count(f) for f in fillers)

def compute_silence_ratio(segments, speaker, total_duration):
    if total_duration == 0:
        return 0.0

    speech_segments = [s for s in segments if s.get("speaker") == speaker]
    speech_time = sum(s["end"] - s["start"] for s in speech_segments)
    return round(1 - (speech_time / total_duration), 2)

def compute_emotion_shift(audio_path, segments):
    emotions = []
    for s in segments:
        text = s.get("text", "").strip()
        if len(text.split()) < 2:
            continue
        result = classifier(text)
        top_emotion = max(result[0], key=lambda x: x['score'])["label"]
        emotions.append(top_emotion)

    shift_score = len(set(emotions)) / len(emotions) if emotions else 0
    return round(shift_score, 2)
