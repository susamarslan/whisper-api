FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UVICORN_WORKERS=2 \
    SAVE_DIR=/var/recordings \
    REDIS_URL=redis://redis:6379/0

# Sistem bağımlılıkları (ffmpeg, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Kayıt klasörü
RUN mkdir -p ${SAVE_DIR}

# Web için default komut (compose tarafında override edilecek)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


