"""
Playto Payout Engine — Models

Design principles:
- Balances are NEVER stored directly. They are always derived from the ledger
  (sum of credit entries minus sum of debit entries). This is the only correct
  way to model money: a stored balance can drift; a derived balance cannot.
- All amounts are in PAISE (integer). Never float, never decimal.
- The LedgerEntry table is append-only. We never update or delete entries.
- Held funds live as a separate concept so available_balance and held_balance
  are always unambiguous.
"""

import uuid
from django.db import models
from django.db.models import Sum, Q
from django.utils import timezone


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    bank_account_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.email})"

    # -------------------------------------------------------------------------
    # Balance helpers — all queries happen at DB level, no Python arithmetic
    # on fetched rows. These methods produce a single SQL aggregation query.
    # -------------------------------------------------------------------------

    def total_credits_paise(self) -> int:
        """Sum of all credit ledger entries for this merchant."""
        result = self.ledger_entries.filter(
            entry_type=LedgerEntry.CREDIT
        ).aggregate(total=Sum("amount_paise"))
        return result["total"] or 0

    def total_debits_paise(self) -> int:
        """Sum of all debit ledger entries for this merchant."""
        result = self.ledger_entries.filter(
            entry_type=LedgerEntry.DEBIT
        ).aggregate(total=Sum("amount_paise"))
        return result["total"] or 0

    def held_balance_paise(self) -> int:
        """
        Funds reserved for payouts currently in PENDING or PROCESSING state.
        These are funds that have been debited from the usable balance but
        not yet settled or returned.
        """
        result = self.payouts.filter(
            status__in=[Payout.PENDING, Payout.PROCESSING]
        ).aggregate(total=Sum("amount_paise"))
        return result["total"] or 0

    def available_balance_paise(self) -> int:
        """
        Credits − Debits. This is the invariant Playto checks.
        Debits include both completed payouts AND held funds (pending/processing).
        """
        return self.total_credits_paise() - self.total_debits_paise()

    class Meta:
        ordering = ["name"]


class LedgerEntry(models.Model):
    """
    Immutable, append-only record of every money movement for a merchant.

    CREDIT: money flowing IN (customer payment, refund reversal, funds returned
            from a failed payout).
    DEBIT:  money flowing OUT (payout initiated — the hold is recorded here
            immediately so available_balance drops atomically with the payout
            creation).
    """

    CREDIT = "credit"
    DEBIT = "debit"
    ENTRY_TYPE_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPE_CHOICES)
    amount_paise = models.BigIntegerField()  # Always positive
    description = models.CharField(max_length=512)
    reference_id = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Links back to the payout or payment that caused this entry"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.entry_type.upper()} ₹{self.amount_paise/100:.2f} — {self.merchant.name}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "entry_type"]),
            models.Index(fields=["merchant", "created_at"]),
        ]


class IdempotencyKey(models.Model):
    """
    Stores previously-seen idempotency keys scoped to a merchant.

    When a request arrives:
    1. Look up (merchant, key). If found and not expired → return cached response.
    2. If in-flight (response_body is null) → return 409 Conflict.
    3. If not found → insert immediately (claiming the key), then process.

    The unique_together constraint on (merchant, key) means two concurrent
    requests with the same key will race to INSERT — the loser gets an
    IntegrityError which we catch and resolve by reading the winner's row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    key = models.CharField(max_length=255)
    # Null until the first request completes — signals "in-flight"
    response_body = models.JSONField(null=True, blank=True)
    response_status = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def is_in_flight(self) -> bool:
        return self.response_body is None

    def __str__(self):
        return f"IdempotencyKey({self.key[:8]}…) for {self.merchant.name}"

    class Meta:
        unique_together = [("merchant", "key")]
        indexes = [
            models.Index(fields=["merchant", "key"]),
            models.Index(fields=["expires_at"]),
        ]


class Payout(models.Model):
    """
    A payout request from a merchant to their bank account.

    State machine (enforced at the model level in transition()):
        PENDING → PROCESSING → COMPLETED
                             → FAILED

    Any backward or skip transition raises ValueError.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]

    # Valid forward transitions only
    VALID_TRANSITIONS = {
        PENDING: {PROCESSING},
        PROCESSING: {COMPLETED, FAILED},
        COMPLETED: set(),   # terminal
        FAILED: set(),      # terminal
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.PROTECT, related_name="payouts"
    )
    amount_paise = models.BigIntegerField()
    bank_account_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    attempt_count = models.IntegerField(default=0)
    idempotency_key = models.CharField(max_length=255, blank=True, null=True)
    failure_reason = models.TextField(blank=True, null=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())

    def transition(self, new_status: str) -> None:
        """
        Enforce state machine at the object level.
        Callers are still responsible for database atomicity (select_for_update).
        """
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Illegal payout state transition: {self.status} → {new_status} "
                f"(payout {self.id})"
            )
        self.status = new_status
        if new_status == self.PROCESSING:
            self.processing_started_at = timezone.now()

    def is_stuck(self) -> bool:
        """
        A payout is 'stuck' if it has been in PROCESSING for more than the
        configured threshold without completing or failing.
        """
        from django.conf import settings
        if self.status != self.PROCESSING or not self.processing_started_at:
            return False
        threshold = settings.PAYOUT_STUCK_THRESHOLD_SECONDS
        elapsed = (timezone.now() - self.processing_started_at).total_seconds()
        return elapsed > threshold

    def __str__(self):
        return f"Payout ₹{self.amount_paise/100:.2f} [{self.status}] — {self.merchant.name}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["merchant", "status"]),
            models.Index(fields=["processing_started_at"]),
        ]
