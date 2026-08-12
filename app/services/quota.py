"""
Quota enforcement. Checked BEFORE a usage event is recorded (see
routers/usage.py) -- an over-quota request never creates a usage_event.

Boundary rule (must be exact, per the brief): a request that lands exactly
ON the limit is allowed. A request that would push usage PAST the limit is
rejected. So the check is `current_usage + requested > limit`, not `>=`.

Two distinct rejection reasons get two distinct status codes:
- 402 Payment Required: the tenant's subscription itself isn't in good
  standing (canceled / past_due) -- no plan would let this through until
  they pay.
- 429 Too Many Requests: the subscription is fine, but this month's quota
  for this usage type is used up.
"""
from dataclasses import dataclass
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import Tenant, UsageEvent, UsageType, SubscriptionStatus


@dataclass
class QuotaResult:
    allowed: bool
    current_usage: int
    limit: int
    requested: int
    status_code: int | None  # None when allowed
    reason: str | None


def _current_usage(db: Session, tenant_id: int, usage_type: UsageType, billing_period: str) -> int:
    if usage_type == UsageType.api_call:
        col = UsageEvent.api_call_quantity
    else:
        # Total token consumption for quota purposes counts every category --
        # this is a *usage* quota, distinct from the cost calculation, which
        # prices each category differently.
        col = (
            UsageEvent.input_tokens
            + UsageEvent.cached_input_tokens
            + UsageEvent.output_tokens
            + UsageEvent.reasoning_tokens
        )
    total = db.execute(
        select(func.coalesce(func.sum(col), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == usage_type,
            UsageEvent.billing_period == billing_period,
        )
    ).scalar_one()
    return int(total)


def check_quota(
    db: Session,
    tenant: Tenant,
    usage_type: UsageType,
    requested_qty: int,
    billing_period: str,
) -> QuotaResult:
    if tenant.subscription_status != SubscriptionStatus.active:
        limit = (
            tenant.plan.monthly_api_call_limit
            if usage_type == UsageType.api_call
            else tenant.plan.monthly_token_limit
        )
        current = _current_usage(db, tenant.id, usage_type, billing_period)
        return QuotaResult(
            allowed=False,
            current_usage=current,
            limit=limit,
            requested=requested_qty,
            status_code=402,
            reason=f"Subscription status is '{tenant.subscription_status.value}'. "
            "Payment is required before this tenant can consume billable resources.",
        )

    limit = (
        tenant.plan.monthly_api_call_limit
        if usage_type == UsageType.api_call
        else tenant.plan.monthly_token_limit
    )
    current = _current_usage(db, tenant.id, usage_type, billing_period)

    if current + requested_qty > limit:
        return QuotaResult(
            allowed=False,
            current_usage=current,
            limit=limit,
            requested=requested_qty,
            status_code=429,
            reason=(
                f"Monthly {usage_type.value} quota exceeded for plan '{tenant.plan.name}': "
                f"{current} used + {requested_qty} requested > {limit} limit."
            ),
        )

    return QuotaResult(
        allowed=True,
        current_usage=current,
        limit=limit,
        requested=requested_qty,
        status_code=None,
        reason=None,
    )
