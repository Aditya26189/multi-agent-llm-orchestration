FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=120 --retries=5 -r requirements.txt

COPY . .

CMD ["sh", "-c", "PYTHONPATH=/app alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info"]
