import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models import Plan, Tenant, SubscriptionStatus


@pytest.fixture()
def db_session():
    # StaticPool pins every checkout to the SAME underlying connection --
    # without it, SQLite's ':memory:' database is scoped per-connection, so
    # a query on a second connection sees an empty (tableless) database even
    # though create_all() just ran. This caused intermittent
    # "no such table" failures until traced down to the pool default.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db_session):
    free = Plan(name="free", monthly_api_call_limit=1000, monthly_token_limit=100_000)
    pro = Plan(name="pro", monthly_api_call_limit=50_000, monthly_token_limit=5_000_000, stripe_price_id="price_sim_pro")
    db_session.add_all([free, pro])
    db_session.flush()

    tenant = Tenant(name="Test Tenant", plan_id=free.id, subscription_status=SubscriptionStatus.active)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return {"free": free, "pro": pro, "tenant": tenant}
