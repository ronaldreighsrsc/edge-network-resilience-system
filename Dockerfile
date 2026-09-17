# Multi-stage Dockerfile for OmniEdge Sentinel Edge Deployment
FROM python:3.12-slim AS base

# Install system utilities for network probing
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    wireless-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and configurations
COPY src/ ./src/
COPY data/ ./data/
COPY config.yaml .
COPY pyproject.toml .

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
