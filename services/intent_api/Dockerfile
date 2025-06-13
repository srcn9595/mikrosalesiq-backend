FROM mikrosalesiq-base

RUN apt-get update && apt-get install -y --no-install-recommends git \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# bağlam = ./services/intent_api, o yüzden dosyalar doğrudan burada
COPY main.py            /app/main.py
COPY tool_manifest.json /app/tool_manifest.json
COPY config/            /app/config/

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
