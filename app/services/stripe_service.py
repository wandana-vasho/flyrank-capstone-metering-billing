"""
Stripe test-mode integration.

$0-stack fallback: signature verification is pure HMAC-SHA256 math against
a shared webhook secret -- Stripe's own `stripe.Webhook.construct_event`
does no network call either. So when no real Stripe account exists yet
(settings.stripe_live is False), we run the EXACT SAME verification
algorithm Stripe uses, against a locally-generated `simulated_webhook_secret`
instead of a real `whsec_...`. Tests sign fake events with `sign_payload()`
the same way the real Stripe CLI (`stripe trigger`) would sign a real one.
When a real key is added to .env later, `create_checkout_session` and event
construction switch to the real `stripe` SDK calls -- nothing else in the
codebase changes.
"""
import hashlib
import hmac
import json
import time
import uuid

import stripe as stripe_sdk

from app.config import settings


class SignatureVerificationError(Exception):
    pass


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Builds a Stripe-CLI-style `Stripe-Signature` header for a payload."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode('utf-8')}"
    signature = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def verify_and_parse_event(payload: bytes, sig_header: str) -> dict:
    """
    Verifies a webhook's signature and returns the parsed event dict.
    Raises SignatureVerificationError on any mismatch or malformed header --
    callers must turn that into an HTTP 400, never a 500 and never a silent
    accept.
    """
    if settings.stripe_live:
        try:
            event = stripe_sdk.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
            return event if isinstance(event, dict) else event.to_dict()
        except (stripe_sdk.error.SignatureVerificationError, ValueError) as exc:
            raise SignatureVerificationError(str(exc)) from exc

    # Simulated path -- same algorithm, local secret.
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        ts, sig = parts["t"], parts["v1"]
    except (KeyError, ValueError) as exc:
        raise SignatureVerificationError("malformed Stripe-Signature header") from exc

    expected = sign_payload(payload, settings.simulated_webhook_secret, int(ts))
    expected_sig = expected.split("v1=")[1]
    if not hmac.compare_digest(expected_sig, sig):
        raise SignatureVerificationError("signature mismatch")

    # Reject stale timestamps the same way Stripe does (replay protection),
    # tolerance matches Stripe's default 5-minute window.
    if abs(int(time.time()) - int(ts)) > 300:
        raise SignatureVerificationError("timestamp outside tolerance")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SignatureVerificationError("invalid JSON payload") from exc


def create_checkout_session(tenant_name: str, price_id: str, success_url: str, cancel_url: str) -> dict:
    """Returns {id, url}. Real Stripe Checkout session if a live key is
    configured, otherwise a locally-fabricated session that still round-trips
    through the same webhook path via build_simulated_checkout_completed_event."""
    if settings.stripe_live:
        session = stripe_sdk.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return {"id": session.id, "url": session.url}

    fake_id = f"cs_test_sim_{uuid.uuid4().hex[:24]}"
    separator = "&" if "?" in success_url else "?"
    return {"id": fake_id, "url": f"{success_url}{separator}session_id={fake_id}&simulated=1"}


def build_simulated_checkout_completed_event(
    session_id: str, tenant_id: int, stripe_customer_id: str, stripe_subscription_id: str
) -> bytes:
    """Builds a fake `checkout.session.completed` event body for local testing --
    stand-in for what `stripe trigger checkout.session.completed` sends."""
    event = {
        "id": f"evt_sim_{uuid.uuid4().hex[:24]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "customer": stripe_customer_id,
                "subscription": stripe_subscription_id,
                "client_reference_id": str(tenant_id),
                "metadata": {"tenant_id": str(tenant_id)},
            }
        },
    }
    return json.dumps(event).encode("utf-8")


def build_simulated_subscription_event(
    event_type: str, tenant_id: int, stripe_subscription_id: str, status: str
) -> bytes:
    """event_type: 'customer.subscription.updated' | 'customer.subscription.deleted'"""
    event = {
        "id": f"evt_sim_{uuid.uuid4().hex[:24]}",
        "type": event_type,
        "data": {
            "object": {
                "id": stripe_subscription_id,
                "status": status,
                "metadata": {"tenant_id": str(tenant_id)},
            }
        },
    }
    return json.dumps(event).encode("utf-8")
