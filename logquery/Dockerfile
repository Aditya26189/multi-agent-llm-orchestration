FROM python:3.12-slim

WORKDIR /app

RUN pip install flask psycopg2-binary

COPY logquery/ .

CMD ["python", "app.py"]
