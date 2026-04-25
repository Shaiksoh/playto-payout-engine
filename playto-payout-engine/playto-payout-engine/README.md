# Playto Payout Engine

A minimal but production-hardened payout engine for Playto Pay. Merchants accumulate balance from international payments and withdraw to their Indian bank accounts.

**Stack:** Django + DRF · PostgreSQL · Celery + Redis · React + Tailwind

---

## Features

- **Merchant Ledger** — append-only, balance always derived (never stored), all amounts in paise
- **Payout API** — idempotent `POST /api/v1/payouts/` with `Idempotency-Key` header
- **Concurrency safety** — `SELECT FOR UPDATE` prevents concurrent overdraft at the DB level
- **State machine** — `pending → processing → completed/failed`, illegal transitions throw
- **Background processing** — Celery worker simulates bank settlement (70% success, 20% fail, 10% stuck)
- **Retry logic** — stuck payouts retried with exponential backoff, max 3 attempts, then failed + funds returned
- **React dashboard** — balance cards, payout form, live status polling every 3s

---

## Quick start with Docker

```bash
git clone https://github.com/<your-username>/playto-payout-engine
cd playto-payout-engine
docker-compose up --build
```

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000/api/v1/
- **Django Admin:** http://localhost:8000/admin/ (create superuser below)

The seed script runs automatically on first boot. Three merchants are created with realistic transaction history.

---

## Manual setup (without Docker)

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- Redis 7+
- Node.js 20+

### Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables (or create a .env file)
export POSTGRES_DB=playto
export POSTGRES_USER=playto
export POSTGRES_PASSWORD=playto
export POSTGRES_HOST=localhost
export REDIS_URL=redis://localhost:6379/0

# Run migrations
python manage.py migrate

# Seed test data
python manage.py seed_merchants

# Create admin user (optional)
python manage.py createsuperuser

# Start Django
python manage.py runserver
```

### Celery worker (separate terminal)

```bash
cd backend
source venv/bin/activate
celery -A playto worker --loglevel=info
```

### Celery Beat scheduler (separate terminal)

```bash
cd backend
source venv/bin/activate
celery -A playto beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

---

## Running tests

```bash
cd backend
python manage.py test payout --verbosity=2
```

Key tests:
- `ConcurrencyTest.test_two_simultaneous_payouts_exactly_one_succeeds` — verifies SELECT FOR UPDATE prevents overdraft
- `IdempotencyTest.test_duplicate_key_returns_same_response` — verifies idempotency
- `StateMachineTest.test_failed_to_completed_raises` — verifies illegal transition is blocked
- `RetryTest.test_exhausted_payout_fails_and_returns_funds` — verifies retry + fund return

---

## API reference

### List merchants
```
GET /api/v1/merchants/
```

### Merchant dashboard (balance + history)
```
GET /api/v1/merchants/<merchant_id>/
```

### Request a payout
```
POST /api/v1/payouts/?merchant_id=<uuid>
Headers:
  Content-Type: application/json
  Idempotency-Key: <uuid>
Body:
  {
    "amount_paise": 50000,
    "bank_account_id": "HDFC0001234"
  }
```

Returns `201 Created` on success, `422` if insufficient balance, `409` if idempotency key is in flight.

### Payout status
```
GET /api/v1/payouts/<payout_id>/
```

### Health check
```
GET /api/v1/health/
```

---

## Seeded test data

Three merchants are created with the seed script:

| Merchant | Bank | Initial Balance |
|---|---|---|
| Arjun Sharma | HDFC0001234567 | ₹6,500 |
| Priya Nair | ICICI9876543210 | ₹3,100 |
| Kiran Reddy | SBI0000987654 | ₹10,200 |

---

## Architecture decisions

See [EXPLAINER.md](./EXPLAINER.md) for a detailed walkthrough of every significant design decision, including the exact locking primitive, idempotency strategy, and an honest AI code audit.

---

## Deployment

The project is deployed at: **[your-deployment-url]**

Deployment notes for Railway / Render:
1. Set `POSTGRES_*` env vars to point at your managed DB
2. Set `REDIS_URL` to your managed Redis
3. Set `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`
4. Backend start command: `python manage.py migrate && python manage.py seed_merchants && gunicorn playto.wsgi:application`
5. Worker start command: `celery -A playto worker --loglevel=info`
6. Beat start command: `celery -A playto beat --scheduler django_celery_beat.schedulers:DatabaseScheduler`
