from fastapi import FastAPI

from app.database import Base, engine
from app.routers import usage, billing, webhooks

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Usage Metering & Billing Engine",
    description="Idempotent metering, quota enforcement, AI-token cost calculation, "
    "and Stripe test-mode subscription sync.",
    version="1.0.0",
)

app.include_router(usage.router)
app.include_router(billing.router)
app.include_router(webhooks.router)


@app.get("/health")
def health():
    return {"status": "ok"}
