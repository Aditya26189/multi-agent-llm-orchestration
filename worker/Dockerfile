FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=120 --retries=5 -r requirements.txt

COPY . .

CMD ["sh", "-c", "PYTHONPATH=/app celery -A worker.celery_app worker --loglevel=info -Q heavy_tasks --concurrency=4"]
