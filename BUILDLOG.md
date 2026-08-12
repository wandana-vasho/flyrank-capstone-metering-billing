# BUILDLOG.md

Honest log of where AI (Claude) helped, where it was wrong and got caught,
and what changed. Per the brief's rule: "The AI wrote it" is not an answer
at the demo — this log exists so I can explain any of it.

## Where AI helped

- Generated the full initial implementation (models, services, routers,
  tests, docs) from the capstone brief in one build session, following the
  layered architecture (routers → services → models) established in earlier
  track assignments.
- Proposed the micro-cents-per-token integer representation for pricing, to
  avoid float rounding error while still supporting sub-cent-per-token
  prices ($0.30/1M tokens) — rounds to whole cents exactly once, at the end
  of a calculation, never mid-calculation.
- Proposed the $0 simulated-Stripe-mode design: HMAC-SHA256 webhook
  signing/verification implemented locally with the exact algorithm Stripe
  itself uses (no network call in either case), so the whole system —
  including the signature-forgery and replay-dedup probes — is buildable
  and testable before any real Stripe account exists. Swapping in a real
  key later is a `.env` change, no code change.

## Where AI was wrong, caught by actually running things, and what changed

**1. Malformed checkout URL (caught running the real demo, not code review).**
`create_checkout_session`'s simulated URL always appended a fresh `?session_id=...`
query param. When the caller's `success_url` already had a `?tenant_id=`
query on it (added by the `/billing/checkout` route), the result was a
literal double-`?` URL: `...success?tenant_id=2?session_id=...`. Only showed
up when I actually ran the checkout endpoint end-to-end with a query-bearing
success_url, not from reading the code. Fixed by checking for an existing
`?` and using `&` instead:
```python
separator = "&" if "?" in success_url else "?"
return {"id": fake_id, "url": f"{success_url}{separator}session_id={fake_id}&simulated=1"}
```

**2. SQLite `:memory:` + `StaticPool` gave a false-positive-looking race result.**
Wrote a concurrency test firing 10 threads at the same idempotency key,
using an in-memory SQLite DB pinned to one connection via `StaticPool` (a
pattern that's normally correct for single-threaded test isolation). Under
real thread concurrency, sharing one Python connection object across
threads isn't safe — the result was 2 threads both reporting `created=True`
even though only 1 row ever landed in the table. The row-count assertion
(the actually-important guarantee) still passed, which is what made this
subtle — the *bookkeeping* was wrong while the *data integrity* was right.
Root-caused to concurrent threads corrupting the shared connection's
transaction state, not to any bug in `metering.record_usage`. Fixed by
switching the concurrency test to a temp-file SQLite DB (`tempfile.mkstemp`)
so each thread gets its own real connection, with `timeout=30` so a thread
waits for SQLite's writer lock instead of racing it. Re-ran 5x after the
fix with no flakiness.

**3. Two wrong expected values in my own pricing test assertions.**
`test_pure_input_tokens` and `test_pure_output_tokens` asserted `3000` and
`25000` cents respectively — I'd mentally computed "$0.30/1M tokens × 1M
tokens" as $30 instead of $0.30 (dropped a factor of 100 converting the
per-token micro-cent price to a total). `pytest` caught it immediately
(`assert 30 == 3000`) since the *implementation* was correct and the *test*
was wrong. Fixed the assertions to the arithmetically correct 30 and 250
cents.

## What I'd flag as worth re-verifying with a real Stripe account

The webhook signature verification, dedup, and event-processing logic runs
through the identical code path whether the secret is real or simulated
(same HMAC-SHA256 algorithm, same `stripe.Webhook.construct_event` call when
`settings.stripe_live` is true) — but the outbound `checkout.session.create`
call against a real Stripe test-mode account has not been exercised in this
submission, since no Stripe account was set up. That's the one piece I'd
call "verified by code symmetry, not by a live run" rather than fully proven.
