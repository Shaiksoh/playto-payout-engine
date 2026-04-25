"""
Playto Payout Engine — Service Layer

This module owns all business logic. Views are thin. Tasks call into here.
Every money-moving operation is wrapped in a database transaction.

The two hardest problems in payout engines:
1. Concurrency: two simultaneous payout requests must not overdraw the balance.
2. Idempotency: a retried request must return the exact same response.

Both are solved here.
"""

import logging
import random
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Sum, F
from django.utils import timezone

from .models import Merchant, LedgerEntry, IdempotencyKey, Payout

logger = logging.getLogger("payout")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def get_or_create_idempotency_key(merchant: Merchant, key: str):
    """
    Returns (idempotency_record, created: bool).

    If the key exists and is not expired → return it (created=False).
    If the key does not exist → INSERT it (created=True), response_body starts null.
    If two threads race to create the same key, one will get IntegrityError;
    that thread re-reads and returns the winner's row (created=False).
    """
    expires_at = timezone.now() + timedelta(seconds=settings.IDEMPOTENCY_KEY_TTL_SECONDS)
    try:
        record, created = IdempotencyKey.objects.get_or_create(
            merchant=merchant,
            key=key,
            defaults={"expires_at": expires_at},
        )
        # If found but expired, treat as new (delete and recreate)
        if not created and record.is_expired():
            record.delete()
            record = IdempotencyKey.objects.create(
                merchant=merchant,
                key=key,
                expires_at=expires_at,
            )
            created = True
        return record, created
    except IntegrityError:
        # Race condition: another thread created this key between our GET and INSERT.
        # Read what they created.
        record = IdempotencyKey.objects.get(merchant=merchant, key=key)
        return record, False


def complete_idempotency_key(record: IdempotencyKey, response_body: dict, status_code: int):
    """Stamp the idempotency key with the final response so retries get it."""
    record.response_body = response_body
    record.response_status = status_code
    record.save(update_fields=["response_body", "response_status"])


# ---------------------------------------------------------------------------
# Payout creation
# ---------------------------------------------------------------------------

def create_payout(
    merchant: Merchant,
    amount_paise: int,
    bank_account_id: str,
    idempotency_key_str: str,
) -> tuple[dict, int]:
    """
    Creates a payout request if the merchant has sufficient available balance.

    The critical section uses SELECT FOR UPDATE on the merchant row to
    serialize concurrent payout requests. Without this lock, two concurrent
    requests can both read the same balance and both succeed, overdrawing.

    Returns (response_dict, http_status_code).
    """
    idem_record, created = get_or_create_idempotency_key(merchant, idempotency_key_str)

    if not created:
        # We've seen this key before
        if idem_record.is_in_flight():
            # First request hasn't finished yet
            return {"error": "Request with this idempotency key is already in progress."}, 409
        # Return the cached response exactly
        logger.info(f"Idempotency hit for key {idempotency_key_str[:8]}… — returning cached response")
        return idem_record.response_body, idem_record.response_status

    # New key — process the request
    try:
        response_body, status_code = _execute_payout_creation(
            merchant, amount_paise, bank_account_id, idempotency_key_str
        )
    except Exception as e:
        # If something blows up, we must clean up the idempotency key so the
        # merchant can retry. Do not leave it in-flight permanently.
        idem_record.delete()
        raise

    complete_idempotency_key(idem_record, response_body, status_code)
    return response_body, status_code


def _execute_payout_creation(
    merchant: Merchant,
    amount_paise: int,
    bank_account_id: str,
    idempotency_key_str: str,
) -> tuple[dict, int]:
    """
    The real work: check balance under lock and debit atomically.

    THE LOCK:
    We use SELECT FOR UPDATE on the Merchant row. This acquires a
    row-level exclusive lock in PostgreSQL. Any concurrent transaction
    that also tries to SELECT FOR UPDATE the same merchant row will
    BLOCK until we commit or rollback. This turns a check-then-act race
    into a serial operation at the database level.

    Python-level locks (threading.Lock, Redis locks) are insufficient here
    because multiple workers may run on different processes or machines.
    Only the database lock is visible to all workers.
    """
    with transaction.atomic():
        # Lock the merchant row for the duration of this transaction.
        # Concurrent requests will queue up here and see updated balances.
        merchant_locked = Merchant.objects.select_for_update().get(pk=merchant.pk)

        available = merchant_locked.available_balance_paise()

        if amount_paise <= 0:
            return {"error": "Amount must be positive."}, 400

        if available < amount_paise:
            logger.warning(
                f"Insufficient balance for {merchant.name}: "
                f"requested {amount_paise} paise, available {available} paise"
            )
            return {
                "error": "Insufficient balance.",
                "available_paise": available,
                "requested_paise": amount_paise,
            }, 422

        # Create the payout record
        payout = Payout.objects.create(
            merchant=merchant_locked,
            amount_paise=amount_paise,
            bank_account_id=bank_account_id,
            status=Payout.PENDING,
            idempotency_key=idempotency_key_str,
        )

        # Record the debit in the ledger immediately.
        # This is what makes available_balance_paise() reflect the hold
        # without a separate "held_balance" column that can drift.
        LedgerEntry.objects.create(
            merchant=merchant_locked,
            entry_type=LedgerEntry.DEBIT,
            amount_paise=amount_paise,
            description=f"Payout initiated to bank account {bank_account_id}",
            reference_id=str(payout.id),
        )

        logger.info(
            f"Payout {payout.id} created for {merchant.name}: "
            f"{amount_paise} paise → {bank_account_id}"
        )

        response_body = _serialize_payout(payout)
        return response_body, 201


# ---------------------------------------------------------------------------
# Payout processing (called by Celery task)
# ---------------------------------------------------------------------------

def process_payout(payout_id: str) -> None:
    """
    Process a single pending payout. Simulates bank settlement.

    This function is idempotent: calling it twice for the same payout in
    PROCESSING state will result in the second call finding the payout
    already past PENDING and doing nothing.
    """
    with transaction.atomic():
        try:
            # Lock the payout row to prevent concurrent task execution
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.error(f"Payout {payout_id} not found")
            return

        if payout.status != Payout.PENDING:
            logger.info(f"Payout {payout_id} is already {payout.status}, skipping")
            return

        payout.attempt_count += 1
        payout.transition(Payout.PROCESSING)
        payout.save(update_fields=["status", "attempt_count", "processing_started_at"])

    # Simulate async bank communication outside the transaction.
    # The payout is in PROCESSING. The background simulation will call
    # finalize_payout() when it "hears back from the bank".
    _simulate_bank_response(payout_id)


def _simulate_bank_response(payout_id: str) -> None:
    """
    Simulates a bank API call. In production this would be an actual HTTP
    call to a banking partner (RazorpayX, Open, etc.).
    """
    roll = random.random()

    if roll < settings.PAYOUT_SUCCESS_RATE:
        # 70% success
        finalize_payout(payout_id, success=True)
    elif roll < settings.PAYOUT_SUCCESS_RATE + settings.PAYOUT_FAIL_RATE:
        # 20% failure
        finalize_payout(payout_id, success=False, reason="Bank rejected: insufficient details")
    else:
        # 10% hang in processing — the retry mechanism will handle this
        logger.info(f"Payout {payout_id} is hanging in processing (simulated)")


def finalize_payout(payout_id: str, success: bool, reason: str = None) -> None:
    """
    Moves a payout from PROCESSING to COMPLETED or FAILED.

    On failure: atomically returns the held funds to the merchant by
    creating a CREDIT ledger entry in the same transaction as the
    status update. These two operations are inseparable.
    """
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().get(id=payout_id)
        except Payout.DoesNotExist:
            logger.error(f"Payout {payout_id} not found during finalization")
            return

        if payout.status != Payout.PROCESSING:
            logger.warning(
                f"finalize_payout called on payout {payout_id} "
                f"with status {payout.status} — skipping"
            )
            return

        if success:
            payout.transition(Payout.COMPLETED)
            payout.save(update_fields=["status", "updated_at"])
            logger.info(f"Payout {payout_id} completed successfully")
        else:
            payout.transition(Payout.FAILED)
            payout.failure_reason = reason or "Bank settlement failed"
            payout.save(update_fields=["status", "failure_reason", "updated_at"])

            # Return the funds atomically with the status change.
            # This is a single transaction: if the credit fails, the status
            # update rolls back too. The merchant is never left with a FAILED
            # payout and missing funds.
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                entry_type=LedgerEntry.CREDIT,
                amount_paise=payout.amount_paise,
                description=f"Refund for failed payout {payout_id}: {payout.failure_reason}",
                reference_id=str(payout_id),
            )
            logger.info(
                f"Payout {payout_id} failed — returned {payout.amount_paise} paise to "
                f"{payout.merchant.name}"
            )


# ---------------------------------------------------------------------------
# Retry mechanism
# ---------------------------------------------------------------------------

def retry_stuck_payouts() -> None:
    """
    Called periodically by Celery Beat. Finds payouts stuck in PROCESSING
    and either retries them or marks them as failed after max attempts.
    """
    from django.conf import settings as s

    threshold = timezone.now() - timedelta(seconds=s.PAYOUT_STUCK_THRESHOLD_SECONDS)

    stuck_payouts = Payout.objects.filter(
        status=Payout.PROCESSING,
        processing_started_at__lt=threshold,
    ).select_for_update(skip_locked=True)  # skip rows locked by other workers

    with transaction.atomic():
        for payout in stuck_payouts:
            if payout.attempt_count >= s.PAYOUT_MAX_ATTEMPTS:
                logger.warning(
                    f"Payout {payout.id} exhausted {s.PAYOUT_MAX_ATTEMPTS} attempts — marking failed"
                )
                payout.transition(Payout.FAILED)
                payout.failure_reason = "Max retry attempts exceeded (bank timeout)"
                payout.save(update_fields=["status", "failure_reason", "updated_at"])

                LedgerEntry.objects.create(
                    merchant=payout.merchant,
                    entry_type=LedgerEntry.CREDIT,
                    amount_paise=payout.amount_paise,
                    description=f"Refund for timed-out payout {payout.id}",
                    reference_id=str(payout.id),
                )
            else:
                # Reset to pending for retry with exponential backoff (handled by task)
                logger.info(
                    f"Retrying stuck payout {payout.id} "
                    f"(attempt {payout.attempt_count}/{s.PAYOUT_MAX_ATTEMPTS})"
                )
                payout.status = Payout.PENDING
                payout.processing_started_at = None
                payout.save(update_fields=["status", "processing_started_at", "updated_at"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_payout(payout: Payout) -> dict:
    return {
        "id": str(payout.id),
        "merchant_id": str(payout.merchant_id),
        "amount_paise": payout.amount_paise,
        "amount_inr": f"{payout.amount_paise / 100:.2f}",
        "bank_account_id": payout.bank_account_id,
        "status": payout.status,
        "attempt_count": payout.attempt_count,
        "failure_reason": payout.failure_reason,
        "created_at": payout.created_at.isoformat(),
        "updated_at": payout.updated_at.isoformat(),
    }


def get_merchant_summary(merchant: Merchant) -> dict:
    """Returns all balance info and recent history for the dashboard."""
    credits = merchant.total_credits_paise()
    debits = merchant.total_debits_paise()
    available = credits - debits

    recent_entries = merchant.ledger_entries.order_by("-created_at")[:20]
    recent_payouts = merchant.payouts.order_by("-created_at")[:20]

    return {
        "merchant": {
            "id": str(merchant.id),
            "name": merchant.name,
            "email": merchant.email,
            "bank_account_id": merchant.bank_account_id,
        },
        "balance": {
            "available_paise": available,
            "available_inr": f"{available / 100:.2f}",
            "held_paise": merchant.held_balance_paise(),
            "held_inr": f"{merchant.held_balance_paise() / 100:.2f}",
            "total_credits_paise": credits,
            "total_debits_paise": debits,
        },
        "ledger": [
            {
                "id": str(e.id),
                "type": e.entry_type,
                "amount_paise": e.amount_paise,
                "amount_inr": f"{e.amount_paise / 100:.2f}",
                "description": e.description,
                "reference_id": e.reference_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in recent_entries
        ],
        "payouts": [_serialize_payout(p) for p in recent_payouts],
    }
