FROM python:3.12-slim

WORKDIR /app

# curl used only for container health checks (no secrets copied into image)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY streamlit_app ./streamlit_app
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[dev]"

ENV PYTHONUNBUFFERED=1 \
    PATIENT_REPOSITORY_PROVIDER=local_json \
    POLICY_RETRIEVER_PROVIDER=local \
    MEDICATION_ORDER_PROVIDER=unavailable \
    ENABLE_DYNAMODB=false \
    ENABLE_OPENSEARCH=false \
    ENABLE_LANGFUSE=false

EXPOSE 8000 8501

CMD ["uvicorn", "cardiologist_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
