"""
Seed demo data: two plans (Free / Pro) and a few tenants, including one
tenant parked one call away from its Free-plan quota so the boundary
behavior is immediately demoable.

Run: python -m scripts.seed
"""
from app.database import Base, engine, SessionLocal
from app.models import Plan, Tenant, SubscriptionStatus, UsageEvent, UsageType
from datetime import datetime, timezone


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Plan).first() is not None:
            print("Already seeded -- skipping. Delete billing.db to reseed.")
            return

        free = Plan(name="free", monthly_api_call_limit=1000, monthly_token_limit=100_000, stripe_price_id="")
        pro = Plan(name="pro", monthly_api_call_limit=50_000, monthly_token_limit=5_000_000, stripe_price_id="price_sim_pro")
        db.add_all([free, pro])
        db.flush()

        acme = Tenant(name="Acme Corp", plan_id=free.id, subscription_status=SubscriptionStatus.active)
        globex = Tenant(name="Globex Inc", plan_id=pro.id, subscription_status=SubscriptionStatus.active)
        initech = Tenant(name="Initech (near quota)", plan_id=free.id, subscription_status=SubscriptionStatus.active)
        db.add_all([acme, globex, initech])
        db.flush()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        # Park Initech at 999/1000 API calls so the very next call demos the
        # exact boundary (allowed at 1000, rejected at 1001).
        db.add(UsageEvent(
            tenant_id=initech.id,
            idempotency_key="seed-bulk-999",
            usage_type=UsageType.api_call,
            billing_period=period,
            api_call_quantity=999,
            cost_cents=999,
        ))
        db.commit()

        print(f"Seeded plans: free(id={free.id}) pro(id={pro.id})")
        print(f"Seeded tenants: acme(id={acme.id}) globex(id={globex.id}) initech(id={initech.id}, 999/1000 API calls used)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
