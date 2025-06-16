FROM mikrosalesiq-base

# İhtiyaç duyulan OS paketleri
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
       ffmpeg \
       libsndfile1 \
       git \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app/

# Python kütüphaneleri
RUN pip install --no-cache-dir \
      fastapi[all] \
      pymongo \
      redis \
      whisperx \
      pyannote.audio \
      soundfile \
      requests \
      python-dotenv

ENV PYTHONUNBUFFERED=1
CMD ["python", "transcribe_worker.py"]
