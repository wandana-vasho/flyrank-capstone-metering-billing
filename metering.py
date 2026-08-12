"""
Idempotent usage metering. This is the heart of the capstone.

Correctness guarantee: for a given (tenant_id, idempotency_key), calling
record_usage() any number of times -- sequentially or concurrently -- results
in exactly one usage_events row. A retried request returns the ORIGINAL
event, not a new one, and does not add to cost or quota a second time.

Two layers make this true:
1. An application-level pre-check: look the key up before inserting.
2. A database-level UNIQUE constraint on (tenant_id, idempotency_key) as the
   real source of truth -- the pre-check alone has a race window between two
   concurrent requests with the same key; the DB constraint is what actually
   closes it. On a race, the loser's INSERT raises IntegrityError, which we
   catch and resolve by re-reading the winner's row instead of erroring out.
"""
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tenant, UsageEvent, UsageType
from app.services.pricing import calculate_token_cost_cents, calculate_api_call_cost_cents


@dataclass
class MeteringResult:
    event: UsageEvent
    created: bool  # False means this was a duplicate -- the original is returned


def _find_existing(db: Session, tenant_id: int, idempotency_key: str) -> UsageEvent | None:
    return (
        db.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key,
        )
        .first()
    )


def record_usage(
    db: Session,
    tenant: Tenant,
    idempotency_key: str,
    usage_type: UsageType,
    billing_period: str,
    api_call_quantity: int = 0,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> MeteringResult:
    if not idempotency_key or not idempotency_key.strip():
        raise ValueError("idempotency_key is required")

    existing = _find_existing(db, tenant.id, idempotency_key)
    if existing is not None:
        return MeteringResult(event=existing, created=False)

    if usage_type == UsageType.api_call:
        cost_cents = calculate_api_call_cost_cents(api_call_quantity)
    else:
        cost_cents = calculate_token_cost_cents(
            input_tokens, cached_input_tokens, output_tokens, reasoning_tokens
        )

    event = UsageEvent(
        tenant_id=tenant.id,
        idempotency_key=idempotency_key,
        usage_type=usage_type,
        billing_period=billing_period,
        api_call_quantity=api_call_quantity,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cost_cents=cost_cents,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent identical request -- the other
        # request's insert won. Roll back our failed insert and return
        # its row instead of surfacing an error.
        db.rollback()
        winner = _find_existing(db, tenant.id, idempotency_key)
        assert winner is not None, "unique violation but no row found -- should be impossible"
        return MeteringResult(event=winner, created=False)

    db.refresh(event)
    return MeteringResult(event=event, created=True)
