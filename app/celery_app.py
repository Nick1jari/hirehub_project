from celery import Celery

from app.config import settings

celery_app = Celery(
    "docqa",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,  # one task at a time per worker — embedding is CPU-heavy
)
