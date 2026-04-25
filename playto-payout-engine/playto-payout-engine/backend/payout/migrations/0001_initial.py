from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Merchant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(unique=True)),
                ("bank_account_id", models.CharField(max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("entry_type", models.CharField(choices=[("credit", "Credit"), ("debit", "Debit")], max_length=10)),
                ("amount_paise", models.BigIntegerField()),
                ("description", models.CharField(max_length=512)),
                ("reference_id", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ledger_entries", to="payout.merchant")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="IdempotencyKey",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.CharField(max_length=255)),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("response_status", models.IntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="idempotency_keys", to="payout.merchant")),
            ],
        ),
        migrations.CreateModel(
            name="Payout",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount_paise", models.BigIntegerField()),
                ("bank_account_id", models.CharField(max_length=100)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed")],
                    default="pending",
                    max_length=20,
                )),
                ("attempt_count", models.IntegerField(default=0)),
                ("idempotency_key", models.CharField(blank=True, max_length=255, null=True)),
                ("failure_reason", models.TextField(blank=True, null=True)),
                ("processing_started_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payouts", to="payout.merchant")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["merchant", "entry_type"], name="payout_ledg_merch_type_idx"),
        ),
        migrations.AddIndex(
            model_name="ledgerentry",
            index=models.Index(fields=["merchant", "created_at"], name="payout_ledg_merch_time_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="idempotencykey",
            unique_together={("merchant", "key")},
        ),
        migrations.AddIndex(
            model_name="idempotencykey",
            index=models.Index(fields=["merchant", "key"], name="payout_idem_merch_key_idx"),
        ),
        migrations.AddIndex(
            model_name="idempotencykey",
            index=models.Index(fields=["expires_at"], name="payout_idem_expires_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["status"], name="payout_payout_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["merchant", "status"], name="payout_payout_merch_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["processing_started_at"], name="payout_payout_proc_time_idx"),
        ),
    ]
