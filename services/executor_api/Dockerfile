# services/executor_api/Dockerfile.transcribe_worker
FROM mikrosalesiq-base

ARG CUDNN_TAR=cudnn-linux-x86_64-8.9.7.29_cuda12-archive.tar.xz
ENV CUDNN_TAR=${CUDNN_TAR}

# 0) Sistem paketleri
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg-dev zlib1g-dev ffmpeg libsndfile1 git \
        curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 1) cuDNN arşivini kopyala
COPY third_party/${CUDNN_TAR} /tmp/

# 2) Arşivi aç, kütüphane + header’ları kopyala, temizle
RUN tar -xJf /tmp/${CUDNN_TAR} -C /tmp && \
    cp -P /tmp/cudnn-*cuda12-archive/lib/libcudnn* /usr/local/lib/ && \
    cp -P /tmp/cudnn-*cuda12-archive/include/cudnn*.h /usr/local/include/ && \
    ldconfig && \
    rm -rf /tmp/${CUDNN_TAR} /tmp/cudnn-*




# 3) ---------- PyTorch wheel’leri (offline) ----------------
# third_party/pytorch/ içinde *.whl dosyaları var
COPY third_party/pytorch/*.whl /tmp/pytorch/

RUN pip install --no-cache-dir --no-index --no-deps \
        --find-links /tmp/pytorch \
        torch==2.5.1+cu124 \
        torchvision==0.20.1+cu124 \
        torchaudio==2.5.1+cu124 \
 && rm -rf /tmp/pytorch
# --------------------------------------------------------

# 4) Proje kodu
WORKDIR /app
COPY . /app/
ENV PYTHONPATH=/app:/app/shared_lib
ENV PYTHONUNBUFFERED=1
CMD ["python", "transcribe_worker.py"]
