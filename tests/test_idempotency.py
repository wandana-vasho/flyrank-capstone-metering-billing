from app.models import UsageType, UsageEvent
from app.services import metering


def test_same_key_twice_creates_exactly_one_row(db_session, seeded):
    tenant = seeded["tenant"]

    r1 = metering.record_usage(
        db_session, tenant, "retry-key-1", UsageType.api_call, "2026-08", api_call_quantity=3
    )
    r2 = metering.record_usage(
        db_session, tenant, "retry-key-1", UsageType.api_call, "2026-08", api_call_quantity=3
    )

    assert r1.created is True
    assert r2.created is False
    assert r1.event.id == r2.event.id

    count = db_session.query(UsageEvent).filter(UsageEvent.idempotency_key == "retry-key-1").count()
    assert count == 1, "double-counting occurred -- exactly one row is required"


def test_different_keys_create_separate_rows(db_session, seeded):
    tenant = seeded["tenant"]
    r1 = metering.record_usage(db_session, tenant, "key-a", UsageType.api_call, "2026-08", api_call_quantity=1)
    r2 = metering.record_usage(db_session, tenant, "key-b", UsageType.api_call, "2026-08", api_call_quantity=1)
    assert r1.event.id != r2.event.id


def test_idempotency_key_required(db_session, seeded):
    tenant = seeded["tenant"]
    import pytest
    with pytest.raises(ValueError):
        metering.record_usage(db_session, tenant, "", UsageType.api_call, "2026-08", api_call_quantity=1)


def test_concurrent_identical_requests_still_create_exactly_one_row(seeded):
    """
    Sequential retries only prove the pre-check works. This proves the
    actual guarantee: fire the SAME idempotency key from many threads at
    once (simulating two racing HTTP retries hitting the server
    simultaneously) and confirm the database's unique constraint -- not
    just application logic -- is what prevents a duplicate row.

    Uses a temp-file SQLite DB (not ':memory:') so each thread gets its own
    real connection. An in-memory DB with StaticPool shares ONE Python
    connection object across all threads, which isn't actually safe for
    concurrent use -- it produced a false result here (two threads both
    reporting created=True) that had nothing to do with the idempotency
    logic and everything to do with the fake single-connection setup.
    A real file gives genuine independent connections, like separate app-
    server workers or Postgres clients would have in production.
    """
    import os
    import tempfile
    import threading
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import Plan, Tenant, SubscriptionStatus, UsageEvent
    from app.services import metering
    from app.models import UsageType

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    try:
        # timeout=30: let a thread WAIT for SQLite's writer lock instead of
        # immediately raising "database is locked" -- we want to test the
        # unique-constraint race, not SQLite's default 5s lock timeout.
        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30}
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        setup = Session()
        plan = Plan(name="free", monthly_api_call_limit=1000, monthly_token_limit=100_000)
        setup.add(plan)
        setup.flush()
        tenant = Tenant(name="Race Tenant", plan_id=plan.id, subscription_status=SubscriptionStatus.active)
        setup.add(tenant)
        setup.commit()
        tenant_id = tenant.id
        setup.close()

        results = []

        def worker():
            session = Session()
            t = session.get(Tenant, tenant_id)
            r = metering.record_usage(session, t, "race-key-1", UsageType.api_call, "2026-08", api_call_quantity=1)
            results.append(r.created)
            session.close()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check = Session()
        count = check.query(UsageEvent).filter(UsageEvent.idempotency_key == "race-key-1").count()
        check.close()

        assert count == 1, f"race condition allowed {count} rows to be created instead of 1"
        assert results.count(True) == 1, "exactly one of the racing requests should be the 'creator'"
        assert results.count(False) == 9, "the other nine must recognize the duplicate, not error out"
    finally:
        # engine.dispose() closes every pooled connection first. Without
        # this, Windows refuses to delete the temp file with a
        # PermissionError ("used by another process") because SQLAlchemy's
        # connection pool still holds it open -- Linux allows removing an
        # open file, which is why this didn't surface in the original
        # sandbox run and only showed up on the real Windows machine.
        engine.dispose()
        os.remove(db_path)


def test_api_end_to_end_idempotent_retry(client, seeded):
    tenant_id = seeded["tenant"].id
    body = {"tenant_id": tenant_id, "idempotency_key": "http-retry-1", "usage_type": "api_call", "api_call_quantity": 4}

    r1 = client.post("/generate", json=body)
    r2 = client.post("/generate", json=body)

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["usage_event_id"] == r2.json()["usage_event_id"]
    assert r1.json()["duplicate"] is False
    assert r2.json()["duplicate"] is True

    usage = client.get(f"/usage?tenant_id={tenant_id}").json()
    assert usage["api_calls_used"] == 4, "a duplicate retry must not double-count usage"