from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, UsageEvent, UsageType
from app.schemas import GenerateRequest, GenerateResponse, UsageSummaryResponse
from app.services import metering, quota

router = APIRouter(tags=["usage"])


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest, db: Session = Depends(get_db)):
    """The one dummy billable endpoint: creates a usage event, enforces
    quota BEFORE recording, and returns the calculated cost."""
    tenant = db.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    usage_type = UsageType(req.usage_type)
    period = _current_period()

    # A retried request with the same idempotency_key must be recognized
    # BEFORE quota is checked -- otherwise a retry of an already-successful
    # call could be wrongly rejected once the tenant is near its limit.
    existing = metering._find_existing(db, tenant.id, req.idempotency_key)
    if existing is not None:
        return GenerateResponse(
            usage_event_id=existing.id,
            duplicate=True,
            cost_cents=existing.cost_cents,
            billing_period=existing.billing_period,
        )

    requested_qty = (
        req.api_call_quantity
        if usage_type == UsageType.api_call
        else req.input_tokens + req.cached_input_tokens + req.output_tokens + req.reasoning_tokens
    )

    result = quota.check_quota(db, tenant, usage_type, requested_qty, period)
    if not result.allowed:
        raise HTTPException(status_code=result.status_code, detail=result.reason)

    metering_result = metering.record_usage(
        db,
        tenant,
        req.idempotency_key,
        usage_type,
        period,
        api_call_quantity=req.api_call_quantity,
        input_tokens=req.input_tokens,
        cached_input_tokens=req.cached_input_tokens,
        output_tokens=req.output_tokens,
        reasoning_tokens=req.reasoning_tokens,
    )
    event = metering_result.event
    return GenerateResponse(
        usage_event_id=event.id,
        duplicate=not metering_result.created,
        cost_cents=event.cost_cents,
        billing_period=event.billing_period,
    )


@router.get("/usage", response_model=UsageSummaryResponse)
def get_usage(tenant_id: int, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    period = _current_period()

    api_calls_used = db.execute(
        select(func.coalesce(func.sum(UsageEvent.api_call_quantity), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == UsageType.api_call,
            UsageEvent.billing_period == period,
        )
    ).scalar_one()

    token_cols = (
        UsageEvent.input_tokens + UsageEvent.cached_input_tokens
        + UsageEvent.output_tokens + UsageEvent.reasoning_tokens
    )
    tokens_used = db.execute(
        select(func.coalesce(func.sum(token_cols), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == UsageType.ai_tokens,
            UsageEvent.billing_period == period,
        )
    ).scalar_one()

    total_cost = db.execute(
        select(func.coalesce(func.sum(UsageEvent.cost_cents), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.billing_period == period,
        )
    ).scalar_one()

    return UsageSummaryResponse(
        tenant_id=tenant.id,
        plan=tenant.plan.name,
        billing_period=period,
        api_calls_used=int(api_calls_used),
        api_calls_limit=tenant.plan.monthly_api_call_limit,
        tokens_used=int(tokens_used),
        tokens_limit=tenant.plan.monthly_token_limit,
        total_cost_cents=int(total_cost),
    )
