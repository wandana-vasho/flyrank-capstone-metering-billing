# Usage Metering & Billing Engine

Idempotent usage metering, quota enforcement, AI-token cost calculation, and
Stripe test-mode subscription sync — the backend service every SaaS needs to
answer: how much has this customer used, what does it cost, and have they
hit their limit?

FlyRank Backend AI Engineering internship — capstone.

## Architecture

```
Client ─► POST /generate (billable action)
  └─► already seen this idempotency_key? ─yes─► return original result
  │                                              (no new event, no double charge)
  └─no
    └─► Quota Check (current usage + requested vs. plan limit)
         ├─ over limit, subscription inactive ──► 402 Payment Required
         ├─ over limit, subscription active   ──► 429 Too Many Requests
         └─ allowed
              └─► record UsageEvent (cost calculated: token category rules
                   applied, integer cents, DB unique constraint on
                   (tenant_id, idempotency_key) as the real dedup guarantee)

Client ─► GET /usage?tenant_id= ──► rollup(usage_events for this month)
                                     → { used, limit, cost } per usage type

Client ─► POST /billing/checkout ──► Stripe Checkout session (test mode,
                                      or simulated if no Stripe key set)

Stripe ─► POST /webhooks/stripe
  ├─► verify signature (forged → 400, nothing changes)
  ├─► seen this Stripe event id before? ─yes─► ignored, no-op
  └─no─► apply to tenant (plan flip / status sync) + log event id
```

Layers: `routers/` (HTTP only) → `services/` (business logic, no HTTP
knowledge) → `models.py` (schema). See [DESIGN.md](DESIGN.md) for the full
design doc and data model.

## Quickstart

Requires Python 3.11+. No Docker, no credit card, no Stripe account needed
to run the full demo — it works out of the box in **simulated Stripe mode**.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python -m scripts.seed          # creates plans + 3 demo tenants, one parked
                                 # at 999/1000 API calls for the boundary demo

uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

Interactive API docs: http://127.0.0.1:8000/docs

Run the tests:

```bash
pytest -v
```

## Demo tenants (from the seed script)

| id | name                  | plan | note                                |
|----|-----------------------|------|--------------------------------------|
| 1  | Acme Corp             | free |                                      |
| 2  | Globex Inc            | pro  |                                      |
| 3  | Initech (near quota)  | free | 999/1000 API calls used — next call demos the exact boundary |

## Try it

```bash
# Record usage (idempotent — replay this exact command and you get the same
# usage_event_id back, not a duplicate)
curl -X POST localhost:8000/generate -H "Content-Type: application/json" \
  -d '{"tenant_id":1,"idempotency_key":"demo-1","usage_type":"api_call","api_call_quantity":5}'

# Push Initech (tenant 3) to exactly its 1000-call limit — allowed
curl -X POST localhost:8000/generate -H "Content-Type: application/json" \
  -d '{"tenant_id":3,"idempotency_key":"demo-boundary-1000","usage_type":"api_call","api_call_quantity":1}'

# One more — rejected with 429
curl -X POST localhost:8000/generate -H "Content-Type: application/json" \
  -d '{"tenant_id":3,"idempotency_key":"demo-boundary-1001","usage_type":"api_call","api_call_quantity":1}'

# Check usage rollup
curl "localhost:8000/usage?tenant_id=1"
```

## Going from simulated to real Stripe

Nothing in the code changes. Add real test-mode keys to `.env` (copy
`.env.example`) — `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`, both free
from https://dashboard.stripe.com/test/apikeys, no card required — and the
app automatically switches `POST /billing/checkout` to create a real Stripe
Checkout session and `POST /webhooks/stripe` to verify against the real
Stripe SDK instead of the local simulated signer. Use the Stripe CLI
(`stripe listen --forward-to localhost:8000/webhooks/stripe`) to forward
real webhook events locally.

## Limitations (honest, per the brief's own instruction)

- No invoicing, proration, or overage billing — explicitly out of core scope
  per the brief's "realistic scope" section; the core exercises every rule
  with 2 plans, 2 usage types, 1 billable endpoint.
- AI token counts are simulated inputs to the pricing function, not derived
  from a real model call — per the brief, this capstone meters numbers, not
  AI usage.
- The Stripe integration has been fully exercised in simulated mode (same
  signature-verification code path Stripe itself uses) but not yet against
  a live Stripe test-mode account — see EVIDENCE.md for exactly which probes
  ran against simulated vs. would need a real account to re-verify.
- SQLite is the default store; a `docker-compose.yml` for Postgres is not
  included in this submission (the brief allows SQLite explicitly for this
  capstone) — swapping is a one-line `DATABASE_URL` change plus a
  `psycopg2-binary` dependency, no code changes.
