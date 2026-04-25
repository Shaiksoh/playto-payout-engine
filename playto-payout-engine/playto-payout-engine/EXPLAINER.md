# EXPLAINER.md

> This document explains the architectural decisions behind the Playto Payout Engine. It answers each question from the challenge brief directly and honestly.

---

## 1. The Ledger

**Balance calculation query:**

```python
# From payout/models.py — Merchant.available_balance_paise()

def available_balance_paise(self) -> int:
    credits = self.ledger_entries.filter(
        entry_type=LedgerEntry.CREDIT
    ).aggregate(total=Sum("amount_paise"))["total"] or 0

    debits = self.ledger_entries.filter(
        entry_type=LedgerEntry.DEBIT
    ).aggregate(total=Sum("amount_paise"))["total"] or 0

    return credits - debits
```

This translates to two SQL queries:
```sql
SELECT COALESCE(SUM(amount_paise), 0) FROM payout_ledgerentry
WHERE merchant_id = %s AND entry_type = 'credit';

SELECT COALESCE(SUM(amount_paise), 0) FROM payout_ledgerentry
WHERE merchant_id = %s AND entry_type = 'debit';
```

**Why this model?**

I chose an append-only ledger over a `balance` column on `Merchant` for a fundamental reason: **a stored balance can drift; a derived balance cannot.**

If the system crashes between updating a payout status and updating a stored balance, they desync permanently and silently. With a ledger, every credit and debit is an immutable row. Recomputing balance from scratch at any time gives the same answer. Auditing is free — you just read the ledger.

Every payout initiation writes a DEBIT immediately in the same transaction as the `Payout` row. Every failed payout writes a CREDIT in the same transaction as the status update. There is no moment where the ledger is inconsistent.

Amounts are stored as `BigIntegerField` in paise (1 INR = 100 paise). No float, no decimal. Floats cannot represent most decimal values exactly — `0.1 + 0.2 != 0.3` in IEEE 754. Integer paise avoids this class of bug entirely.

---

## 2. The Lock

**Exact code preventing concurrent overdraft:**

```python
# From payout/services.py — _execute_payout_creation()

with transaction.atomic():
    # This is the critical section.
    # SELECT FOR UPDATE acquires a row-level exclusive lock on the merchant row
    # in PostgreSQL. Any other transaction that reaches this line for the same
    # merchant will BLOCK until we commit or rollback.
    merchant_locked = Merchant.objects.select_for_update().get(pk=merchant.pk)

    available = merchant_locked.available_balance_paise()

    if available < amount_paise:
        return {"error": "Insufficient balance.", ...}, 422

    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(entry_type=LedgerEntry.DEBIT, ...)
    # Transaction commits → lock released → next waiter unblocks
```

**The database primitive: `SELECT FOR UPDATE`**

PostgreSQL's `SELECT FOR UPDATE` is a pessimistic row-level lock. When thread A acquires it, thread B's `SELECT FOR UPDATE` on the same row will block at the database level — not the Python level — until A's transaction commits or rolls back.

After A commits, B unblocks and re-reads the balance. By now, A's debit ledger entry exists, so B sees the reduced balance and correctly rejects its own payout if it would overdraw.

**Why not a Python-level lock (threading.Lock / asyncio.Lock)?**

Python locks only work within a single process. Celery workers run as separate processes, potentially on separate machines. Only the database is the shared coordinator visible to all workers. Python-level locks give you false safety in production.

**Why not a Redis lock (Redlock)?**

Redis locks are valid for this use case but add complexity and a failure mode (Redis going down). Since we already have a database transaction, the database lock is simpler, more correct, and removes a dependency. I prefer the minimal primitive.

---

## 3. The Idempotency

**How the system recognizes a seen key:**

```python
# From payout/services.py — get_or_create_idempotency_key()

def get_or_create_idempotency_key(merchant, key):
    expires_at = timezone.now() + timedelta(seconds=settings.IDEMPOTENCY_KEY_TTL_SECONDS)
    try:
        record, created = IdempotencyKey.objects.get_or_create(
            merchant=merchant,
            key=key,
            defaults={"expires_at": expires_at},
        )
        ...
    except IntegrityError:
        # Race condition: two requests arrived simultaneously with the same key.
        # One INSERT won; we lost. Read the winner's row.
        record = IdempotencyKey.objects.get(merchant=merchant, key=key)
        return record, False
```

The `IdempotencyKey` table has a `unique_together` constraint on `(merchant, key)`. When a request arrives:

1. **Key not seen**: `get_or_create` INSERTs a new row with `response_body=None` (in-flight). Process the request. When complete, write the response to this row.
2. **Key seen, completed**: Return `record.response_body` and `record.response_status` verbatim — exactly the same JSON with the same payout ID.
3. **Key seen, in-flight** (`response_body is None`): Return 409 Conflict. The first request is still running.

**If the first request is still in flight when the second arrives:**

The second request reads `response_body = None` on the existing row and returns 409 Conflict immediately. The client knows to wait and retry. It will get the real response once the first request commits.

Keys are scoped per merchant — the unique constraint is on `(merchant_id, key)`, not just `key`. Merchant A's key `abc` and Merchant B's key `abc` are independent.

Keys expire after 24 hours. Expired keys are deleted and the slot is freed, consistent with standard behavior (Stripe uses 24h).

---

## 4. The State Machine

**Where failed → completed is blocked:**

```python
# From payout/models.py — Payout

VALID_TRANSITIONS = {
    PENDING: {PROCESSING},
    PROCESSING: {COMPLETED, FAILED},
    COMPLETED: set(),   # terminal — no exits
    FAILED: set(),      # terminal — no exits
}

def transition(self, new_status: str) -> None:
    if not self.can_transition_to(new_status):
        raise ValueError(
            f"Illegal payout state transition: {self.status} → {new_status} "
            f"(payout {self.id})"
        )
    self.status = new_status
    ...
```

`FAILED` maps to an empty set. `can_transition_to(COMPLETED)` returns `False`. `transition(COMPLETED)` raises `ValueError`.

This check lives on the model itself, not in a view or service. That means it fires regardless of where `transition()` is called from — API, Celery task, admin action, or a future webhook handler. You can't route around it.

In `finalize_payout()`, the state change and the ledger credit for fund return happen in the same `transaction.atomic()` block:

```python
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(id=payout_id)
    # If status is not PROCESSING, transition() will raise → rollback
    payout.transition(Payout.FAILED)
    payout.save(...)
    # Credit only written if transition succeeded
    LedgerEntry.objects.create(entry_type=LedgerEntry.CREDIT, ...)
```

If the state transition is illegal, the exception propagates, the transaction rolls back, and no credit entry is created. Atomicity is guaranteed.

---

## 5. The AI Audit

I used Claude (Anthropic) throughout this project. Here is one specific case where it generated subtly wrong code.

**What AI gave me (initial services.py draft):**

```python
def create_payout(merchant, amount_paise, bank_account_id, idempotency_key_str):
    # Check idempotency first
    idem_record = IdempotencyKey.objects.filter(
        merchant=merchant, key=idempotency_key_str
    ).first()
    
    if idem_record and not idem_record.is_expired():
        return idem_record.response_body, idem_record.response_status

    with transaction.atomic():
        available = merchant.available_balance_paise()  # ← BUG
        if available < amount_paise:
            return {"error": "Insufficient balance"}, 422
        
        payout = Payout.objects.create(...)
        LedgerEntry.objects.create(...)
    
    # Save idempotency response
    IdempotencyKey.objects.create(
        merchant=merchant, key=idempotency_key_str, ...
    )
    return _serialize_payout(payout), 201
```

**Two bugs I caught:**

**Bug 1 — Missing lock.** `merchant.available_balance_paise()` is called inside `transaction.atomic()` but without `select_for_update()`. The transaction provides atomicity for writes but not isolation for reads. Two concurrent transactions can both read the same balance (both see 10000 paise), both pass the `available < amount_paise` check, and both create payouts. The SELECT FOR UPDATE on the merchant row is not optional — it's what serializes concurrent access.

**Bug 2 — Race condition in idempotency.** The AI's version checked for an existing key with a separate SELECT before the main transaction. Between that SELECT and the INSERT at the end, two threads with the same key can both find no existing record and both proceed to create a payout. The create at the end would then hit an IntegrityError, but a duplicate payout has already been created and the ledger has already been debited. By the time the error fires, the damage is done.

**What I replaced it with:**

The fix uses `get_or_create` with the database's unique constraint as the arbiter:
- The first thread to INSERT wins and gets `created=True`.
- The second thread gets `created=False` and reads the first thread's (in-flight) record.
- The `select_for_update()` on the merchant row is added inside the payout creation transaction.

These two fixes together mean: idempotency is resolved at the database level before the lock is acquired, and the lock prevents concurrent overdraft even when idempotency keys are different.

---

## Architecture summary

```
POST /api/v1/payouts/
    │
    ├─ Validate Idempotency-Key (get_or_create with DB unique constraint)
    │   ├─ Seen + complete → return cached response
    │   ├─ Seen + in-flight → 409
    │   └─ New → continue
    │
    ├─ transaction.atomic() + SELECT FOR UPDATE (merchant)
    │   ├─ available_balance = SUM(credits) - SUM(debits)
    │   ├─ available < amount → 422 Insufficient Balance
    │   └─ Create Payout + LedgerEntry(DEBIT) in same tx
    │
    ├─ Stamp idempotency record with response
    └─ Enqueue process_payout_task.delay(payout_id)

process_payout_task (Celery)
    │
    ├─ PENDING → PROCESSING (with lock)
    └─ Simulate bank (70% success / 20% fail / 10% hang)
        ├─ Success → PROCESSING → COMPLETED
        └─ Failure → PROCESSING → FAILED + LedgerEntry(CREDIT) in same tx

retry_stuck_payouts_task (Celery Beat, every 30s)
    └─ Find PROCESSING payouts older than threshold
        ├─ attempt_count < max → reset to PENDING
        └─ attempt_count >= max → FAILED + LedgerEntry(CREDIT)
```

The invariant `SUM(credits) - SUM(debits) == available_balance` holds at every point because: credits and debits are the only source of truth, and every state transition that should change the balance (payout created, payout failed) writes a ledger entry atomically with the state change.
