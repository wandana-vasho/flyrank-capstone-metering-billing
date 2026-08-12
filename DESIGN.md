# Design — Usage Metering & Billing Engine

## Problem

Every SaaS backend needs to answer three questions per tenant: how much have
they used, what does that cost, and have they hit their plan's limits? This
service answers all three, and does it correctly under the conditions that
actually break naive implementations: a retried request, a webhook delivered
twice, a usage count landing exactly on the quota boundary.

## Data model

```
Plan            (id, name, monthly_api_call_limit, monthly_token_limit, stripe_price_id)
Tenant          (id, name, plan_id -> Plan, stripe_customer_id, subscription_status)
UsageEvent      (id, tenant_id -> Tenant, idempotency_key, usage_type,
                  api_call_quantity,
                  input_tokens, cached_input_tokens, output_tokens, reasoning_tokens,
                  cost_cents, billing_period, created_at)
                UNIQUE (tenant_id, idempotency_key)  <- the exactly-once guarantee
WebhookEvent    (id, stripe_event_id UNIQUE, event_type, processed_at)  <- webhook dedup
```

Two usage types share one table (`usage_type` discriminator) rather than two
tables, because the metering and idempotency logic is identical for both —
only the cost calculation branches. Token categories are stored as separate
columns (not summed at write time) because they price differently and the
quota rollup, cost rollup, and evidence trail all need the breakdown.

## API surface

- `POST /generate` — the one billable action. Body carries `tenant_id`,
  `idempotency_key`, `usage_type`, and the relevant quantity fields. Order of
  operations inside the handler: (1) check for an existing row with this
  idempotency key — if found, return it immediately, before quota is even
  checked, so a retry near the quota boundary can't be wrongly rejected; (2)
  check quota; (3) record the event (which re-checks idempotency at the DB
  level as the real source of truth — see `services/metering.py`).
- `GET /usage?tenant_id=` — rollup for the tenant's current calendar-month
  billing period: used/limit for both usage types, total cost.
- `POST /billing/checkout` — creates a Stripe Checkout session (test mode, or
  simulated when no Stripe key is configured yet).
- `POST /webhooks/stripe` — signature-verified, deduplicated event receiver.

## Layers

```
routers/      HTTP concerns only: parse request, call a service, map the
              result to a status code. No business logic here.
services/     metering.py   — idempotent recording
              quota.py      — boundary-exact allow/reject decisions
              pricing.py    — pure functions, pinned constants, no I/O
              stripe_service.py     — checkout + signature verify (real or simulated)
              webhook_processor.py — applies a verified event to the DB, with dedup
models.py     SQLAlchemy schema — the only place table structure is defined
```

Swapping the database (SQLite → Postgres) or the payment provider touches
only `database.py`/`config.py` and `stripe_service.py` respectively — no
route or service logic changes.

## Non-goal

Real payments. Stripe test mode only, by design (see § 3 of the brief) — no
code path in this repo can move real money, and the app refuses to start in
"live" billing mode without both a real secret key and webhook secret
present, which a developer has to deliberately configure.
