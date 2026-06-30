FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Uploaded files live here; mount a volume to persist them (the database is Postgres).
RUN mkdir -p /data
ENV DATABASE_URL=postgresql+psycopg2://meerato:meerato@db:5432/meerato \
    UPLOAD_DIR=/data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
