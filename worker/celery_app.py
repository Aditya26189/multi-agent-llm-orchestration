import os
from celery import Celery

app = Celery("mega_ai", broker=os.environ["REDIS_URL"])

app.conf.update(
    broker_transport_options={"visibility_timeout": 3600},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
)
