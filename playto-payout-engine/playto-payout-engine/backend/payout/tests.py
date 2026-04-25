"""
Tests for Playto Payout Engine.

We focus on the two hardest correctness properties:
1. Concurrency: two simultaneous 60-rupee payouts from a 100-rupee balance
   → exactly one succeeds, one is rejected.
2. Idempotency: duplicate requests with the same key return identical responses.

We also verify the state machine and ledger invariant.
"""

import uuid
import threading
import time
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from unittest.mock import patch

from payout.models import Merchant, LedgerEntry, Payout, IdempotencyKey
from payout.services import (
    create_payout,
    finalize_payout,
    get_merchant_summary,
    retry_stuck_payouts,
)


def make_merchant(name="Test Merchant", balance_paise=10_000) -> Merchant:
    """Helper: create a merchant with a seeded credit balance."""
    m = Merchant.objects.create(
        name=name,
        email=f"{uuid.uuid4()}@test.com",
        bank_account_id="HDFC0001234",
    )
    if balance_paise:
        LedgerEntry.objects.create(
            merchant=m,
            entry_type=LedgerEntry.CREDIT,
            amount_paise=balance_paise,
            description="Test seed credit",
        )
    return m


# ---------------------------------------------------------------------------
# Ledger invariant tests
# ---------------------------------------------------------------------------

class LedgerInvariantTest(TestCase):
    def test_available_balance_equals_credits_minus_debits(self):
        """
        Core invariant: available_balance = total_credits - total_debits.
        Balance must never be read from a stored column — it's always derived.
        """
        merchant = make_merchant(balance_paise=50_000)  # ₹500

        # Add another credit
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.CREDIT,
            amount_paise=20_000,
            description="Second payment",
        )
        # Add a debit
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.DEBIT,
            amount_paise=15_000,
            description="Manual debit",
        )

        self.assertEqual(merchant.total_credits_paise(), 70_000)
        self.assertEqual(merchant.total_debits_paise(), 15_000)
        self.assertEqual(merchant.available_balance_paise(), 55_000)

    def test_float_amounts_never_used(self):
        """All stored amounts should be integers in paise."""
        merchant = make_merchant(balance_paise=99_999)
        entry = merchant.ledger_entries.first()
        self.assertIsInstance(entry.amount_paise, int)

    def test_insufficient_balance_rejected(self):
        merchant = make_merchant(balance_paise=5_000)  # ₹50
        response, code = create_payout(
            merchant=merchant,
            amount_paise=10_000,  # ₹100 — more than balance
            bank_account_id="HDFC0001",
            idempotency_key_str=str(uuid.uuid4()),
        )
        self.assertEqual(code, 422)
        self.assertIn("Insufficient balance", response["error"])
        # No payout created
        self.assertEqual(Payout.objects.filter(merchant=merchant).count(), 0)


# ---------------------------------------------------------------------------
# Concurrency test — THE critical test
# ---------------------------------------------------------------------------

class ConcurrencyTest(TransactionTestCase):
    """
    TransactionTestCase (not TestCase) because we need real transactions that
    commit to the database. TestCase wraps everything in a single transaction
    that never commits, so SELECT FOR UPDATE doesn't work correctly in tests.
    """

    def test_two_simultaneous_payouts_exactly_one_succeeds(self):
        """
        Scenario: merchant has ₹100 (10000 paise).
        Two concurrent requests each try to withdraw ₹60 (6000 paise).
        Exactly ONE must succeed. The other must be rejected with 422.

        This test would fail WITHOUT the SELECT FOR UPDATE lock because:
        - Thread 1 reads balance = 10000
        - Thread 2 reads balance = 10000 (before thread 1 commits)
        - Both see 10000 >= 6000, both succeed → account overdrawn
        """
        merchant = make_merchant(balance_paise=10_000)  # ₹100

        results = []
        errors = []
        barrier = threading.Barrier(2)  # Forces both threads to start simultaneously

        def attempt_payout(key):
            try:
                barrier.wait()  # Both threads hit this simultaneously
                response, code = create_payout(
                    merchant=merchant,
                    amount_paise=6_000,  # ₹60
                    bank_account_id="HDFC0001",
                    idempotency_key_str=key,
                )
                results.append((code, response))
            except Exception as e:
                errors.append(e)

        key1 = str(uuid.uuid4())
        key2 = str(uuid.uuid4())

        t1 = threading.Thread(target=attempt_payout, args=(key1,))
        t2 = threading.Thread(target=attempt_payout, args=(key2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Unexpected errors: {errors}")
        self.assertEqual(len(results), 2, "Expected exactly 2 results")

        status_codes = sorted([r[0] for r in results])
        self.assertIn(201, status_codes, "At least one payout should succeed")
        self.assertIn(422, status_codes, "At least one payout should be rejected")

        # The ledger must reflect exactly one debit of 6000 paise
        debits = LedgerEntry.objects.filter(
            merchant=merchant, entry_type=LedgerEntry.DEBIT
        )
        self.assertEqual(debits.count(), 1, "Exactly one debit should be recorded")
        self.assertEqual(debits.first().amount_paise, 6_000)

        # Available balance should be 10000 - 6000 = 4000
        self.assertEqual(merchant.available_balance_paise(), 4_000)

    def test_exact_balance_payout_succeeds(self):
        """Edge case: withdrawing the exact available balance should work."""
        merchant = make_merchant(balance_paise=5_000)
        response, code = create_payout(
            merchant=merchant,
            amount_paise=5_000,
            bank_account_id="HDFC0001",
            idempotency_key_str=str(uuid.uuid4()),
        )
        self.assertEqual(code, 201)
        self.assertEqual(merchant.available_balance_paise(), 0)


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------

class IdempotencyTest(TransactionTestCase):
    def test_duplicate_key_returns_same_response(self):
        """
        Calling the same endpoint twice with the same Idempotency-Key must
        return identical responses. No duplicate payout created.
        """
        merchant = make_merchant(balance_paise=20_000)
        key = str(uuid.uuid4())

        response1, code1 = create_payout(
            merchant=merchant,
            amount_paise=5_000,
            bank_account_id="ICICI001",
            idempotency_key_str=key,
        )
        response2, code2 = create_payout(
            merchant=merchant,
            amount_paise=5_000,
            bank_account_id="ICICI001",
            idempotency_key_str=key,
        )

        self.assertEqual(code1, 201)
        self.assertEqual(code2, 201)
        self.assertEqual(response1["id"], response2["id"], "Must return same payout ID")

        # Only ONE payout in the database
        payouts = Payout.objects.filter(merchant=merchant)
        self.assertEqual(payouts.count(), 1)

        # Only ONE debit ledger entry
        debits = LedgerEntry.objects.filter(
            merchant=merchant, entry_type=LedgerEntry.DEBIT
        )
        self.assertEqual(debits.count(), 1)

    def test_different_keys_create_different_payouts(self):
        """Two different idempotency keys should create two separate payouts."""
        merchant = make_merchant(balance_paise=20_000)

        _, code1 = create_payout(
            merchant=merchant,
            amount_paise=3_000,
            bank_account_id="SBI001",
            idempotency_key_str=str(uuid.uuid4()),
        )
        _, code2 = create_payout(
            merchant=merchant,
            amount_paise=3_000,
            bank_account_id="SBI001",
            idempotency_key_str=str(uuid.uuid4()),
        )

        self.assertEqual(code1, 201)
        self.assertEqual(code2, 201)
        self.assertEqual(Payout.objects.filter(merchant=merchant).count(), 2)

    def test_key_scoped_to_merchant(self):
        """Same key used by two different merchants should create two payouts."""
        merchant1 = make_merchant(name="M1", balance_paise=10_000)
        merchant2 = make_merchant(name="M2", balance_paise=10_000)
        shared_key = str(uuid.uuid4())

        _, code1 = create_payout(
            merchant=merchant1,
            amount_paise=1_000,
            bank_account_id="SBI001",
            idempotency_key_str=shared_key,
        )
        _, code2 = create_payout(
            merchant=merchant2,
            amount_paise=1_000,
            bank_account_id="SBI001",
            idempotency_key_str=shared_key,
        )

        self.assertEqual(code1, 201)
        self.assertEqual(code2, 201)  # Different merchant, same key → allowed


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------

class StateMachineTest(TestCase):
    def test_valid_transitions_succeed(self):
        merchant = make_merchant()
        payout = Payout.objects.create(
            merchant=merchant, amount_paise=1_000,
            bank_account_id="HDFC", status=Payout.PENDING
        )
        payout.transition(Payout.PROCESSING)
        self.assertEqual(payout.status, Payout.PROCESSING)
        payout.transition(Payout.COMPLETED)
        self.assertEqual(payout.status, Payout.COMPLETED)

    def test_illegal_transition_raises(self):
        merchant = make_merchant()
        payout = Payout.objects.create(
            merchant=merchant, amount_paise=1_000,
            bank_account_id="HDFC", status=Payout.COMPLETED
        )
        with self.assertRaises(ValueError):
            payout.transition(Payout.PENDING)  # completed → pending is illegal

    def test_failed_to_completed_raises(self):
        """The exact transition the spec says must be blocked."""
        merchant = make_merchant()
        payout = Payout.objects.create(
            merchant=merchant, amount_paise=1_000,
            bank_account_id="HDFC", status=Payout.FAILED
        )
        with self.assertRaises(ValueError):
            payout.transition(Payout.COMPLETED)

    def test_failed_payout_returns_funds_atomically(self):
        """
        When a payout fails, funds must return to the merchant in the SAME
        transaction as the status change. Both happen or neither does.
        """
        merchant = make_merchant(balance_paise=10_000)

        # Create and process payout
        response, _ = create_payout(
            merchant=merchant,
            amount_paise=3_000,
            bank_account_id="HDFC",
            idempotency_key_str=str(uuid.uuid4()),
        )
        payout = Payout.objects.get(id=response["id"])
        payout.transition(Payout.PROCESSING)
        payout.save()

        balance_before_failure = merchant.available_balance_paise()

        # Simulate failure
        finalize_payout(str(payout.id), success=False, reason="Bank rejected")

        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.FAILED)

        # Balance should be restored
        balance_after_failure = merchant.available_balance_paise()
        self.assertEqual(
            balance_after_failure,
            balance_before_failure + 3_000,
            "Funds must be returned on failure"
        )

        # Verify the credit entry exists
        refund_entry = LedgerEntry.objects.filter(
            merchant=merchant,
            entry_type=LedgerEntry.CREDIT,
            reference_id=str(payout.id),
        ).first()
        self.assertIsNotNone(refund_entry, "A credit ledger entry must be created on failure")
        self.assertEqual(refund_entry.amount_paise, 3_000)


# ---------------------------------------------------------------------------
# Retry / stuck payout tests
# ---------------------------------------------------------------------------

class RetryTest(TransactionTestCase):
    def test_stuck_payout_is_retried(self):
        """A payout stuck in PROCESSING past the threshold gets reset to PENDING."""
        merchant = make_merchant(balance_paise=10_000)
        response, _ = create_payout(
            merchant=merchant,
            amount_paise=2_000,
            bank_account_id="HDFC",
            idempotency_key_str=str(uuid.uuid4()),
        )
        payout = Payout.objects.get(id=response["id"])
        payout.transition(Payout.PROCESSING)
        # Force processing_started_at into the past
        payout.processing_started_at = timezone.now() - timezone.timedelta(seconds=60)
        payout.attempt_count = 1
        payout.save()

        retry_stuck_payouts()

        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.PENDING, "Should be reset to pending for retry")

    def test_exhausted_payout_fails_and_returns_funds(self):
        """A payout that has used all retries must be marked FAILED and funds returned."""
        from django.conf import settings
        merchant = make_merchant(balance_paise=10_000)
        response, _ = create_payout(
            merchant=merchant,
            amount_paise=2_000,
            bank_account_id="HDFC",
            idempotency_key_str=str(uuid.uuid4()),
        )
        payout = Payout.objects.get(id=response["id"])
        payout.transition(Payout.PROCESSING)
        payout.processing_started_at = timezone.now() - timezone.timedelta(seconds=60)
        payout.attempt_count = settings.PAYOUT_MAX_ATTEMPTS  # exhausted
        payout.save()

        balance_before = merchant.available_balance_paise()
        retry_stuck_payouts()

        payout.refresh_from_db()
        self.assertEqual(payout.status, Payout.FAILED)
        self.assertGreater(merchant.available_balance_paise(), balance_before)
