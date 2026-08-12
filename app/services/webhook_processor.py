"""
Applies a verified Stripe event to our database. Verification (signature +
parsing) already happened in stripe_service.verify_and_parse_event -- by the
time an event reaches this module it is *authentic*, but it might still be
a REPLAY of an event we already processed. That's what WebhookEvent dedup
guards against: Stripe (and its CLI's `stripe trigger --forward-to`) can and
does redeliver events, and processing the same subscription-created event
twice must be a no-op, not a double-apply.
"""
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tenant, Plan, WebhookEvent, SubscriptionStatus


@dataclass
class WebhookResult:
    processed: bool  # False means this event_id was already seen (duplicate, ignored)
    detail: str


def _already_processed(db: Session, event_id: str) -> bool:
    return db.query(WebhookEvent).filter(WebhookEvent.stripe_event_id == event_id).first() is not None


def process_event(db: Session, event: dict) -> WebhookResult:
    event_id = event["id"]
    event_type = event["type"]

    if _already_processed(db, event_id):
        return WebhookResult(processed=False, detail=f"event {event_id} already processed -- ignored")

    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        tenant_id = int(obj.get("client_reference_id") or obj["metadata"]["tenant_id"])
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"tenant {tenant_id} not found")
        pro_plan = db.query(Plan).filter(Plan.name == "pro").first()
        tenant.plan_id = pro_plan.id
        tenant.stripe_customer_id = obj.get("customer", tenant.stripe_customer_id)
        tenant.subscription_status = SubscriptionStatus.active
        detail = f"tenant {tenant_id} upgraded to pro via checkout"

    elif event_type == "customer.subscription.updated":
        tenant_id = int(obj["metadata"]["tenant_id"])
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"tenant {tenant_id} not found")
        status_map = {
            "active": SubscriptionStatus.active,
            "past_due": SubscriptionStatus.past_due,
            "canceled": SubscriptionStatus.canceled,
            "unpaid": SubscriptionStatus.past_due,
        }
        tenant.subscription_status = status_map.get(obj.get("status", "active"), SubscriptionStatus.active)
        detail = f"tenant {tenant_id} subscription status -> {tenant.subscription_status.value}"

    elif event_type == "customer.subscription.deleted":
        tenant_id = int(obj["metadata"]["tenant_id"])
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"tenant {tenant_id} not found")
        free_plan = db.query(Plan).filter(Plan.name == "free").first()
        tenant.plan_id = free_plan.id
        tenant.subscription_status = SubscriptionStatus.canceled
        detail = f"tenant {tenant_id} downgraded to free (subscription deleted)"

    else:
        detail = f"event type {event_type} received, no handler -- acknowledged only"

    log = WebhookEvent(stripe_event_id=event_id, event_type=event_type)
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent redelivery of the same event id.
        db.rollback()
        return WebhookResult(processed=False, detail=f"event {event_id} already processed -- ignored")

    return WebhookResult(processed=True, detail=detail)
