"""
Celery tasks for the payout engine.

Tasks are kept thin — all logic lives in services.py.
"""

import logging
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="payout.tasks.process_payout_task",
)
def process_payout_task(self, payout_id: str) -> None:
    """
    Picks up a single pending payout and processes it.

    Exponential backoff on retry: 10s, 20s, 40s.
    After 3 failures the task gives up and lets retry_stuck_payouts_task
    handle cleanup on its next run.
    """
    from .services import process_payout

    logger.info(f"Processing payout {payout_id} (attempt {self.request.retries + 1})")
    try:
        process_payout(payout_id)
    except Exception as exc:
        logger.exception(f"Payout task failed for {payout_id}: {exc}")
        # Exponential backoff: delay doubles each retry
        retry_delay = 10 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=retry_delay)


@shared_task(name="payout.tasks.retry_stuck_payouts_task")
def retry_stuck_payouts_task() -> None:
    """
    Periodic task (runs every 30 seconds via Celery Beat) that finds payouts
    stuck in PROCESSING and either retries or fails them.
    """
    from .services import retry_stuck_payouts

    logger.info("Checking for stuck payouts...")
    retry_stuck_payouts()


@shared_task(name="payout.tasks.enqueue_pending_payouts")
def enqueue_pending_payouts() -> None:
    """
    Safety net: finds any PENDING payouts not yet picked up and enqueues them.
    Runs every 15 seconds.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import Payout

    # Payouts that have been pending for more than 5 seconds without being picked up
    threshold = timezone.now() - timedelta(seconds=5)
    orphaned = Payout.objects.filter(
        status=Payout.PENDING,
        created_at__lt=threshold,
    ).values_list("id", flat=True)

    count = 0
    for payout_id in orphaned:
        process_payout_task.delay(str(payout_id))
        count += 1

    if count:
        logger.info(f"Enqueued {count} orphaned pending payouts")
