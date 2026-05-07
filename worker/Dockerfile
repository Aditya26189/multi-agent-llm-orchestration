FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "-Q", "heavy_tasks", "--concurrency=4"]
