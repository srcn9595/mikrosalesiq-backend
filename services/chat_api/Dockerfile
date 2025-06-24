FROM mikrosalesiq-base
WORKDIR /app
COPY ./services/chat_api /app
COPY ./shared_lib /app/shared_lib 
ENV PYTHONPATH=/app:/app/shared_lib
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
