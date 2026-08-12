from app.services.stripe_service import (
    build_simulated_checkout_completed_event,
    build_simulated_subscription_event,
    sign_payload,
)
from app.config import settings
from app.models import SubscriptionStatus


def _post_webhook(client, payload: bytes, sig: str):
    return client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": sig},
    )


def test_valid_checkout_webhook_upgrades_tenant(client, seeded, db_session):
    tenant = seeded["tenant"]
    payload = build_simulated_checkout_completed_event(
        "cs_test_1", tenant_id=tenant.id, stripe_customer_id="cus_1", stripe_subscription_id="sub_1"
    )
    sig = sign_payload(payload, settings.simulated_webhook_secret)

    r = _post_webhook(client, payload, sig)
    assert r.status_code == 200
    assert r.json()["processed"] is True

    db_session.refresh(tenant)
    assert tenant.plan.name == "pro"
    assert tenant.stripe_customer_id == "cus_1"


def test_forged_signature_rejected_400_and_no_change(client, seeded, db_session):
    tenant = seeded["tenant"]
    payload = build_simulated_checkout_completed_event(
        "cs_test_2", tenant_id=tenant.id, stripe_customer_id="cus_2", stripe_subscription_id="sub_2"
    )
    forged_sig = "t=1700000000,v1=0000000000000000000000000000000000000000000000000000000000deadbeef"

    r = _post_webhook(client, payload, forged_sig)
    assert r.status_code == 400

    db_session.refresh(tenant)
    assert tenant.plan.name == "free", "a forged webhook must never change tenant state"


def test_malformed_signature_header_rejected_400(client, seeded):
    payload = b'{"id": "evt_x", "type": "checkout.session.completed", "data": {"object": {}}}'
    r = _post_webhook(client, payload, "not-a-valid-header")
    assert r.status_code == 400


def test_replayed_valid_event_processed_once(client, seeded, db_session):
    tenant = seeded["tenant"]
    payload = build_simulated_checkout_completed_event(
        "cs_test_3", tenant_id=tenant.id, stripe_customer_id="cus_3", stripe_subscription_id="sub_3"
    )
    sig = sign_payload(payload, settings.simulated_webhook_secret)

    r1 = _post_webhook(client, payload, sig)
    r2 = _post_webhook(client, payload, sig)  # same event id, replayed

    assert r1.json()["processed"] is True
    assert r2.json()["processed"] is False
    assert "already processed" in r2.json()["detail"]


def test_subscription_deleted_downgrades_to_free(client, seeded, db_session):
    tenant = seeded["tenant"]
    tenant.plan_id = seeded["pro"].id
    db_session.commit()

    payload = build_simulated_subscription_event(
        "customer.subscription.deleted", tenant_id=tenant.id, stripe_subscription_id="sub_x", status="canceled"
    )
    sig = sign_payload(payload, settings.simulated_webhook_secret)
    r = _post_webhook(client, payload, sig)

    assert r.status_code == 200
    db_session.refresh(tenant)
    assert tenant.plan.name == "free"
    assert tenant.subscription_status == SubscriptionStatus.canceled


def test_subscription_updated_past_due(client, seeded, db_session):
    tenant = seeded["tenant"]
    payload = build_simulated_subscription_event(
        "customer.subscription.updated", tenant_id=tenant.id, stripe_subscription_id="sub_y", status="past_due"
    )
    sig = sign_payload(payload, settings.simulated_webhook_secret)
    r = _post_webhook(client, payload, sig)

    assert r.status_code == 200
    db_session.refresh(tenant)
    assert tenant.subscription_status == SubscriptionStatus.past_due
