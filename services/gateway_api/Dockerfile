FROM mikrosalesiq-base

WORKDIR /app
COPY . /app


# ENV PATH /opt/conda/envs/deep_sercan/bin:$PATH

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--log-level", "debug"]

