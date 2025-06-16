FROM mikrosalesiq-base

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir fastapi[all] pymongo

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
