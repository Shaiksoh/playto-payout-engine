from django.apps import AppConfig


class PayoutConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payout"

    def ready(self):
        # Register periodic tasks on startup
        self._setup_periodic_tasks()

    def _setup_periodic_tasks(self):
        """
        Set up Celery Beat periodic tasks programmatically.
        This runs after the app is ready, so database is available.
        """
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule
            import json

            # Retry stuck payouts every 30 seconds
            schedule_30s, _ = IntervalSchedule.objects.get_or_create(
                every=30, period=IntervalSchedule.SECONDS
            )
            PeriodicTask.objects.update_or_create(
                name="Retry stuck payouts",
                defaults={
                    "task": "payout.tasks.retry_stuck_payouts_task",
                    "interval": schedule_30s,
                    "args": json.dumps([]),
                },
            )

            # Enqueue orphaned pending payouts every 15 seconds
            schedule_15s, _ = IntervalSchedule.objects.get_or_create(
                every=15, period=IntervalSchedule.SECONDS
            )
            PeriodicTask.objects.update_or_create(
                name="Enqueue pending payouts",
                defaults={
                    "task": "payout.tasks.enqueue_pending_payouts",
                    "interval": schedule_15s,
                    "args": json.dumps([]),
                },
            )
        except Exception:
            # Tables may not exist yet during initial migration
            pass
