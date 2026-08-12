import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, BigInteger, ForeignKey, DateTime, UniqueConstraint, Enum, Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class UsageType(str, enum.Enum):
    api_call = "api_call"
    ai_tokens = "ai_tokens"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    canceled = "canceled"
    past_due = "past_due"


class Plan(Base):
    """A billing plan. Quotas are per calendar month."""
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # "free" | "pro"
    monthly_api_call_limit: Mapped[int] = mapped_column(Integer)
    monthly_token_limit: Mapped[int] = mapped_column(BigInteger)
    stripe_price_id: Mapped[str] = mapped_column(String(120), default="")


class Tenant(Base):
    """One customer organization. All usage/billing data is scoped to a tenant."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    plan: Mapped["Plan"] = relationship()

    stripe_customer_id: Mapped[str] = mapped_column(String(120), default="")
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageEvent(Base):
    """
    One recorded row of billable activity. The unique constraint on
    (tenant_id, idempotency_key) is what makes metering exactly-once: a
    retried request with the same key hits the constraint and the service
    returns the original row instead of inserting a new one.
    """
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    usage_type: Mapped[UsageType] = mapped_column(Enum(UsageType))

    # api_call usage
    api_call_quantity: Mapped[int] = mapped_column(Integer, default=0)

    # ai_tokens usage -- broken out because each category prices differently
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, default=0)

    cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # integer cents, never float
    billing_period: Mapped[str] = mapped_column(String(7), index=True)  # "YYYY-MM"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookEvent(Base):
    """
    Dedup log for Stripe webhook events. Stripe's own event `id` is the
    natural idempotency key for webhooks -- a unique constraint on it is
    what makes replay-handling a no-op instead of a double-apply.
    """
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
