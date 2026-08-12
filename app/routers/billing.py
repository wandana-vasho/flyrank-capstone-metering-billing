from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, Plan
from app.schemas import CheckoutRequest, CheckoutResponse
from app.services.stripe_service import create_checkout_session

router = APIRouter(tags=["billing"])


@router.post("/billing/checkout", response_model=CheckoutResponse)
def start_checkout(req: CheckoutRequest, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    target = db.query(Plan).filter(Plan.name == req.target_plan).first()
    if target is None:
        raise HTTPException(status_code=400, detail=f"unknown plan '{req.target_plan}'")

    session = create_checkout_session(
        tenant_name=tenant.name,
        price_id=target.stripe_price_id or "price_sim_pro",
        success_url=f"{req.success_url}?tenant_id={tenant.id}",
        cancel_url=req.cancel_url,
    )
    return CheckoutResponse(checkout_session_id=session["id"], checkout_url=session["url"])
