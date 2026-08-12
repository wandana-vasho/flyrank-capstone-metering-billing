from app.models import SubscriptionStatus


def test_request_exactly_at_limit_is_allowed(client, seeded):
    tenant_id = seeded["tenant"].id  # free plan: 1000 api_call limit
    r = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "bulk-1000",
        "usage_type": "api_call", "api_call_quantity": 1000,
    })
    assert r.status_code == 200
    assert r.json()["duplicate"] is False


def test_request_just_under_limit_then_one_more_is_allowed(client, seeded):
    tenant_id = seeded["tenant"].id
    r1 = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "part-1",
        "usage_type": "api_call", "api_call_quantity": 999,
    })
    assert r1.status_code == 200
    r2 = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "part-2",
        "usage_type": "api_call", "api_call_quantity": 1,
    })
    assert r2.status_code == 200, "999 + 1 = 1000 must be allowed (exactly at the limit)"


def test_request_over_limit_is_rejected_429(client, seeded):
    tenant_id = seeded["tenant"].id
    client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "bulk-1000",
        "usage_type": "api_call", "api_call_quantity": 1000,
    })
    r = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "one-too-many",
        "usage_type": "api_call", "api_call_quantity": 1,
    })
    assert r.status_code == 429
    assert "quota exceeded" in r.json()["detail"]


def test_rejected_request_does_not_create_usage_event(client, seeded, db_session):
    from app.models import UsageEvent
    tenant_id = seeded["tenant"].id
    client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "bulk-1000",
        "usage_type": "api_call", "api_call_quantity": 1000,
    })
    client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "rejected-one",
        "usage_type": "api_call", "api_call_quantity": 1,
    })
    exists = db_session.query(UsageEvent).filter(UsageEvent.idempotency_key == "rejected-one").first()
    assert exists is None, "a quota-rejected request must not be recorded as usage"


def test_inactive_subscription_returns_402(client, seeded, db_session):
    tenant = seeded["tenant"]
    tenant.subscription_status = SubscriptionStatus.past_due
    db_session.commit()

    r = client.post("/generate", json={
        "tenant_id": tenant.id, "idempotency_key": "past-due-1",
        "usage_type": "api_call", "api_call_quantity": 1,
    })
    assert r.status_code == 402


def test_token_quota_boundary(client, seeded):
    tenant_id = seeded["tenant"].id  # free plan: 100_000 token limit
    r1 = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "tok-1",
        "usage_type": "ai_tokens", "input_tokens": 99_000, "output_tokens": 1000,
    })
    assert r1.status_code == 200  # exactly 100_000

    r2 = client.post("/generate", json={
        "tenant_id": tenant_id, "idempotency_key": "tok-2",
        "usage_type": "ai_tokens", "input_tokens": 1,
    })
    assert r2.status_code == 429
